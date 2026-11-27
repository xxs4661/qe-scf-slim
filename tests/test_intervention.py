from __future__ import annotations

import unittest

from _paths import ROOT
from scfopt.diagnostics import diagnose
from scfopt.intervention import assess_intervention


def decision(*lines):
    return assess_intervention(diagnose(["Program PWSCF v.7.5", *lines]))


def exhausted(values):
    lines = ["Self-consistent Calculation"]
    for i, value in enumerate(values, 1):
        lines.extend([f"iteration # {i} beta= 0.70", f"estimated scf accuracy < {value} Ry"])
    return [*lines, f"convergence NOT achieved after {len(values)} iterations: stopping", "JOB DONE."]


class InterventionTests(unittest.TestCase):
    def test_real_silicon_results(self):
        for name, priority, code in (("si-converged", "none", "converged"),
                                     ("si-maxstep", "intervene", "short_iteration_budget")):
            with self.subTest(name=name):
                text = (ROOT / "examples" / (name + ".out")).read_text().splitlines()
                result = assess_intervention(diagnose(text))
                self.assertEqual((result["priority"], result["code"]), (priority, code))
                self.assertTrue(all(1 <= n <= len(text) for n in result["evidence_lines"]))
                if priority == "intervene":
                    self.assertIn("convergence NOT achieved", text[result["evidence_lines"][0] - 1])

    def test_repeated_rebounds_cite_actual_measurements_and_limit(self):
        lines = exhausted([1, .2, .9, .1, 1.3, .4, .9, 1.4])
        result = decision(*lines)
        self.assertEqual(result["code"], "repeated_rebounds")
        self.assertIn("one retry", result["next_action"])
        # The program banner occupies line 1; raw input lines start at 2.
        cited = [lines[n - 2] for n in result["evidence_lines"]]
        self.assertEqual(sum("estimated scf accuracy" in text for text in cited), 8)
        self.assertIn("convergence NOT achieved", cited[-1])

    def test_avoid_mixing_diagnosis_from_noise_or_declining_envelope(self):
        for values in ([5, 5, 5, 5, 5, 5, 5, 5], [1, 0, 2, 0, 3, 0, 2, 0],
                       [1, .99, 1.01, .98, 1.02, 1, 1.01, 1], [1, .01, .1, .001, .02, .0001, .001, .0001]):
            with self.subTest(values=values):
                result = decision(*exhausted(values))
                self.assertNotEqual(result["code"], "repeated_rebounds")
                self.assertNotIn("mixing_beta", result["next_action"])
        self.assertEqual(decision(*exhausted([1, .5, .3, .1, .08, .02]))["code"], "improving_at_limit")

    def test_missing_measurements_do_not_turn_stale_history_into_a_beta_trial(self):
        lines = exhausted([1, .1, 1, .1, 1, .1, 1, 1])
        for changed in ([x.replace("iteration # 2", "iteration # 1") for x in lines],
                        [*lines[:-2], "iteration # 9", "estimated scf accuracy < ****** Ry",
                         "convergence NOT achieved after 9 iterations", "JOB DONE."]):
            self.assertNotEqual(decision(*changed)["code"], "repeated_rebounds")

    def test_live_truncated_and_stopped_runs_get_distinct_actions(self):
        for extra, priority, code in (
            (["iteration # 1 beta=0.7"], "review", "check_job_state"),
            (["convergence has been achieved in 8 iterations"], "review", "check_job_state"),
            (["JOB DONE."], "review", "missing_scf_outcome"),
            (["Maximum CPU time exceeded", "JOB DONE."], "intervene", "time_limit"),
            (["Program stopped by user request", "JOB DONE."], "review", "stop_requested"),
            (["Band Structure Calculation"], "review", "unsupported"),
        ):
            with self.subTest(extra=extra):
                result = decision(*extra)
                self.assertEqual((result["priority"], result["code"]), (priority, code))

    def test_fatal_errors_override_residual_trend(self):
        for extra, code in ((["Error in routine readpp (1)", "file Si.UPF not found"], "pseudopotential_error"),
                            (["slurmstepd: oom-kill event"], "out_of_memory"),
                            (["slurmstepd: CANCELLED DUE TO TIME LIMIT"], "time_limit"),
                            (["MPI_ABORT"], "runtime_error"),
                            (["! total energy = NaN Ry"], "nonfinite_result")):
            with self.subTest(extra=extra):
                result = decision(*exhausted([1, .1, 1, .1, 1, .1, 1, 1])[:-2], *extra)
                self.assertEqual(result["code"], code)
                self.assertEqual(result["priority"], "intervene")
                self.assertNotIn("mixing_beta", result["next_action"])

    def test_early_warnings_and_final_band_warnings(self):
        warning = "c_bands: 4 eigenvalues not converged"
        end = ["convergence has been achieved in 8 iterations", "JOB DONE."]
        self.assertEqual(decision("iteration # 1", warning, *end)["priority"], "none")
        self.assertEqual(decision("iteration # 7", warning, *end)["code"], "late_band_warning")
        result = decision("convergence threshold = 1e-8", "estimated scf accuracy < 0.01 Ry", *end)
        self.assertEqual(result["code"], "threshold_check")

    def test_new_invocation_excludes_prior_failure(self):
        lines = [*exhausted([1, .1, 1, .1, 1, .1, 1, 1]), "Program PWSCF v.7.5",
                 "convergence has been achieved in 5 iterations", "JOB DONE."]
        result = decision(*lines)
        self.assertEqual(result["priority"], "none")
        self.assertTrue(all(n > len(lines) - 2 for n in result["evidence_lines"]))

    def test_active_snapshot_rebounds_prompt_status_check_with_evidence(self):
        # Compare the identical history as a snapshot, a clean stop, and a terminal failure.
        values = [4, 3, 2.7, 1.5, 1, .2, .9, .1, 1.3, .4, .9, 1.4]
        lines = exhausted(values)
        result = decision(*lines[:-2])
        self.assertEqual((result["priority"], result["code"]), ("review", "monitor_rebounds"))
        self.assertIn("scheduler", result["next_action"])
        self.assertFalse(any(word in result["next_action"].lower() for word in ("kill", "stop", "restart", "retry")))
        measurements = [lines[n - 2] for n in result["evidence_lines"]]
        self.assertEqual(len(measurements), 8)
        self.assertTrue(all("estimated scf accuracy" in entry for entry in measurements))
        self.assertEqual(decision(*lines)["code"], "repeated_rebounds")
        self.assertEqual(decision(*lines[:-2], "Maximum CPU time exceeded")["code"], "time_limit")
        self.assertEqual(decision(*lines[:-2], "convergence has been achieved in 12 iterations")["code"], "check_job_state")
        for trace in (values[4:], [1 / 2**i for i in range(12)], [.9, .1, .9, .1] * 2 + [0, .1, 0, .1]):
            result = decision(*exhausted(trace)[:-2])
            self.assertEqual(result["code"], "check_job_state")

    def test_only_sizable_late_negative_rho_prompts_density_review(self):
        end = ["convergence has been achieved in 8 iterations", "JOB DONE."]
        for step, amounts, code in ((8, "1.01D-1 0.00E+0", "late_negative_rho"),
                                    (7, "0.00 -0.121", "late_negative_rho"),
                                    (7, "0.01 0.001", "converged"),
                                    (1, "0.23 0.3", "converged"),
                                    (7, "******* 0.2", "converged")):
            with self.subTest(step=step, amounts=amounts):
                result = decision(f"iteration # {step} beta= 0.7", f"negative rho (up, down): {amounts}", *end)
                self.assertEqual(result["code"], code)
                if code == "late_negative_rho":
                    self.assertEqual(result["priority"], "review")
                    self.assertIn(3, result["evidence_lines"])
                    self.assertIn("0.1 electrons", result["reason"])
