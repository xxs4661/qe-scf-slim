from __future__ import annotations

import json
import unittest

from _paths import ROOT
from scfopt.diagnostics import diagnose


def analyze(*lines: str) -> dict:
    return diagnose(iter(lines))


BANNER = "     Program PWSCF v.7.5 starts on 2Oct2024 at 11:22:33"
START = "     Self-consistent Calculation"
ACCURACY = "     estimated scf accuracy < 0.001 Ry"
CONVERGED = "     convergence has been achieved in   3 iterations"
DONE = "   JOB DONE."


class DiagnosticsTests(unittest.TestCase):
    def test_real_pwscf_with_and_without_convergence(self):
        for filename, status, steps, accuracy in (
            ("si-converged.out", "converged", 10, 4.7e-9),
            ("si-maxstep.out", "unconverged", 2, 0.01224138),
        ):
            with self.subTest(filename=filename):
                lines = (ROOT / "examples" / filename).read_text().splitlines()
                report = diagnose(lines)
                self.assertEqual(report["status"], status)
                self.assertTrue(report["job_done"])
                self.assertEqual(report["iterations"], steps)
                self.assertEqual(report["residual_ry"], accuracy)
                self.assertEqual(report["threshold_ry"], 1e-8)
                self.assertEqual(report["residual_operator"], "<")
                self.assertEqual(len(report["history"]), steps)
                self.assertEqual(report["mixing_beta"], 0.5)
                self.assertGreater(report["wall_seconds"], 0)
                self.assertEqual(report["energy_ry"] is None, status == "unconverged")
                for event in report["evidence"]:
                    self.assertEqual(lines[event["line"] - 1].strip(), event["text"])

    def test_truncated_after_convergence_and_clean_stop(self):
        self.assertEqual(analyze(BANNER, START, CONVERGED)["status"], "incomplete")
        self.assertEqual(analyze(BANNER, CONVERGED, "Maximum CPU time exceeded", DONE)["status"], "incomplete")
        self.assertEqual(analyze(BANNER, "Program stopped by user request", DONE)["status"], "incomplete")
        self.assertEqual(analyze(BANNER, DONE)["status"], "incomplete")

    def test_restart_uses_latest_banner_and_absolute_lines(self):
        report = analyze(BANNER, START, ACCURACY, CONVERGED, DONE, BANNER, START, "iteration # 1")
        self.assertEqual((report["status"], report["runs"], report["cycles"]), ("incomplete", 2, 1))
        self.assertFalse(report["job_done"])
        self.assertIsNone(report["residual_ry"])
        self.assertTrue(all(event["line"] >= 6 for event in report["evidence"]))

    def test_implicit_restart_and_new_cycles_reset_metrics(self):
        initial = [BANNER, START, "iteration # 3 beta= 0.4", ACCURACY, "! total energy = -13.5 Ry", CONVERGED]
        for separator, runs, cycles in (([DONE, START], 2, 1), ([START], 1, 2), ([], 1, 2)):
            with self.subTest(separator=separator):
                report = analyze(*initial, *separator, "iteration # 1")
                self.assertEqual((report["status"], report["runs"], report["cycles"]), ("incomplete", runs, cycles))
                self.assertIsNone(report["energy_ry"])
                self.assertIsNone(report["residual_ry"])
                self.assertIsNone(report["mixing_beta"])
                self.assertEqual(report["history"], [])

    def test_known_unsupported_modes_never_use_inner_convergence_as_success(self):
        for marker in ("BFGS Geometry Optimization", "Molecular Dynamics Calculation", "Band Structure Calculation",
                       "EXX self-consistency reached", "Calculation (EXX) stopped after iteration # 3"):
            with self.subTest(marker=marker):
                self.assertEqual(analyze(BANNER, START, CONVERGED, marker, DONE)["status"], "unsupported")
        report = analyze(BANNER, CONVERGED, DONE, "Program PHONON v.7.5 starts on ...", DONE)
        self.assertEqual((report["status"], report["runs"], report["cycles"]), ("unsupported", 2, 0))
        self.assertEqual(analyze("ordinary log", "JOB DONE.")["status"], "unsupported")
        self.assertEqual(analyze("convergence has been achieved", DONE)["status"], "unsupported")

    def test_fatal_evidence_and_advice(self):
        report = analyze(BANNER, "   Error in routine readpp (1):", "file Si.UPF not found", "%%%%%%")
        self.assertEqual(report["status"], "failed")
        self.assertIn("ATOMIC_SPECIES", report["advice"][0])
        self.assertEqual(report["evidence"][-1], {"kind": "error_detail", "line": 3, "text": "file Si.UPF not found"})
        self.assertEqual(analyze(BANNER, CONVERGED, DONE, "slurmstepd: error: Detected 1 oom-kill event")["status"], "failed")
        self.assertEqual(analyze(BANNER, "Message from routine setup:", CONVERGED, DONE)["status"], "converged")

    def test_numerical_formats_and_observed_beta_changes(self):
        report = analyze(
            BANNER, START, "iteration # 2 beta=0.45", "estimated scf accuracy < 3.0D-04 Ry",
            "iteration # 3 beta=0.25", "estimated scf accuracy = 0.0 Ry", "! total energy = -1.23D+01 Ry",
            CONVERGED, "PWSCF   :   2h30m CPU   1d 2h 1m 3.50s WALL", DONE,
        )
        self.assertEqual(report["energy_ry"], -12.3)
        self.assertEqual(report["history"], [
            {"iteration": 2, "residual_ry": 3e-4, "operator": "<", "line": 4},
            {"iteration": 3, "residual_ry": 0.0, "operator": "=", "line": 6},
        ])
        self.assertEqual((report["residual_ry"], report["residual_operator"]), (0.0, "="))
        self.assertEqual(report["wall_seconds"], 93663.5)
        self.assertEqual(report["mixing_betas"], [0.45, 0.25])
        self.assertEqual(report["mixing_beta"], 0.25)

    def test_bad_numbers_cannot_leak_previous_estimates_or_nonfinite_json(self):
        report = analyze(BANNER, START, ACCURACY, "estimated scf accuracy < NaN Ry",
                         "! total energy = ******** Ry", "PWSCF : 2s CPU rubbish WALL", DONE)
        json.dumps(report, allow_nan=False)
        self.assertIsNone(report["residual_ry"])
        self.assertIsNone(report["energy_ry"])
        self.assertIsNone(report["wall_seconds"])

    def test_reported_convergence_above_threshold_keeps_qe_verdict(self):
        for prefix in ("scf ", ""):
            report = analyze(BANNER, prefix + "convergence threshold = 1.0E-08", ACCURACY, CONVERGED, DONE)
            self.assertEqual(report["status"], "converged")
            self.assertIn("scf_must_converge", report["advice"][0])

    def test_late_outcome_cannot_reuse_previous_job_footer(self):
        report = analyze(BANNER, START, ACCURACY, CONVERGED, DONE, CONVERGED)
        self.assertEqual((report["status"], report["runs"], report["job_done"]), ("incomplete", 2, False))
        self.assertIsNone(report["residual_ry"])

    def test_unconverged_history_describes_changes_and_prioritizes_input_limits(self):
        def advice(values):
            records = [f"estimated scf accuracy < {value} Ry" for value in values]
            report = analyze(BANNER, START, *records, f"convergence NOT achieved after {len(values)} iterations: stopping", DONE)
            self.assertIn("electron_maxstep", report["advice"][0])
            self.assertIn("conv_thr", report["advice"][0])
            return " ".join(report["advice"])

        self.assertIn("decrease from 0.05 to 0.01 Ry", advice([0.05, 0.01]))
        once = advice([0.01, 0.005, 0.009])
        self.assertIn("rose from 0.005 to 0.009 Ry", once)
        self.assertNotIn("mixing_beta", once)
        self.assertIn("2 decreases followed by increases", advice([0.01, 0.001, 0.015, 0.002, 0.01]))
        self.assertIn("equal at the printed precision", advice([0.01] * 5))

    def test_diag_and_density_warnings_keep_bounded_evidence_and_do_not_downgrade(self):
        warning = "c_bands:  3 eigenvalues not converged"
        rho = "negative rho (up, down):  3.100E-05 0.000E+00"
        report = analyze(BANNER, rho, START, "iteration # 1", warning, "iteration # 2", warning,
                         "iteration # 3", rho, CONVERGED, DONE)
        self.assertEqual(report["status"], "converged")
        self.assertEqual(report["warnings"]["c_bands"],
                         {"count": 2, "first_line": 5, "last_line": 7, "last_iteration": 2, "last_cycle": 1})
        self.assertEqual(report["warnings"]["negative_rho"]["count"], 2)
        warning_events = [event for event in report["evidence"] if event["kind"] in ("c_bands", "negative_rho")]
        self.assertEqual([event["line"] for event in warning_events], [7, 9])
        self.assertTrue(any("final two" in msg for msg in report["advice"]))
        self.assertTrue(any("ecutrho" in msg for msg in report["advice"]))
        early = analyze(BANNER, START, "iteration # 1", warning, CONVERGED, DONE)
        self.assertTrue(any("Early warnings" in msg for msg in early["advice"]))
        self.assertEqual(analyze(BANNER, warning, DONE, BANNER)["warnings"], {})

    def test_legacy_wall_and_fatal_messages(self):
        self.assertEqual(analyze(BANNER, "PWSCF : cpu 1.0s wall 2.5s")["wall_seconds"], 2.5)
        for msg in ("charge is NaN", "diagonalization (subsp) failed", "Stopped in routine foo", "STOP CRITICAL"):
            with self.subTest(msg=msg):
                self.assertEqual(analyze(BANNER, msg)["status"], "failed")

    def test_final_explicit_nonfinite_value_overrides_convergence(self):
        for field in ("! total energy =", "estimated scf accuracy <"):
            for value in ("NaN", "+Inf", "-Infinity"):
                with self.subTest(field=field, value=value):
                    report = analyze(BANNER, START, f"{field} {value} Ry", CONVERGED, DONE)
                    self.assertEqual(report["status"], "failed")
                    self.assertIn("NaN or infinity", report["advice"][0])
                    json.dumps(report, allow_nan=False)
            current = analyze(BANNER, START, f"{field} NaN Ry", f"{field} 0.01 Ry", CONVERGED, DONE)
            self.assertEqual(current["status"], "converged")
            placeholder = analyze(BANNER, START, f"{field} ******** Ry", CONVERGED, DONE)
            self.assertEqual(placeholder["status"], "converged")
            self.assertTrue(placeholder["advice"])

    def test_corrupt_iteration_number_does_not_abort_diagnosis(self):
        corrupt = "9" * 5000
        report = analyze(BANNER, START, f"iteration # {corrupt}", f"convergence NOT achieved after {corrupt} iterations", DONE)
        self.assertEqual(report["status"], "unconverged")
        self.assertIsNone(report["iterations"])
