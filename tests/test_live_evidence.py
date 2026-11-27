from __future__ import annotations

from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import Mock, patch

from _paths import SCF_SLIM  # noqa: F401
from scfopt.guards import GuardCfg, GuardState, guard_evaluate_step
from scfopt.process_monitor import ProcessMonitor
from scfopt.utils import compute_s4
from scfopt.workflow import build_recommendation, maybe_clone_seed, probe_record, reserve_output_dir


class LiveEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.log = self.root / "scf.out"
        self.proc = Mock(returncode=0)
        self.proc.poll.return_value = 0
        self.monitor = ProcessMonitor(Mock(), self.proc, self.log, self.root, "si",
                                      GuardCfg(), GuardState(), 60, False)

    def test_confirm_actual_adjacent_values_in_one_read(self):
        cfg = GuardCfg(target_residual_ry=1e-4, near_confirm_tail=2)
        state = GuardState()
        residuals = [1e-3, 1e-5, 1e-2, 1e-5, 1e-5]
        reason, _ = guard_evaluate_step(residuals, 5, 0.1, 60, cfg, state)
        self.assertIsNone(reason)
        reason, _ = guard_evaluate_step(residuals + [1e-5], 6, 0.1, 60, cfg, state)
        self.assertEqual(reason, "near_target_done")

    def test_split_marker_and_final_drain(self):
        self.log.write_bytes(b"iteration #1\nestimated scf accuracy < 1.0D-")
        offset = self.monitor._read_new_output(0)
        self.assertEqual(self.monitor.residuals, [])
        with self.log.open("ab") as fout:
            fout.write(b"5 Ry\nconvergence has been achieved")
        self.monitor._read_new_output(offset, final=True)
        self.assertEqual(self.monitor.residuals, [1e-5])
        self.assertTrue(self.monitor.success_flag)
        self.assertFalse(self.monitor._final_result(1)["success"])

    def test_finished_process_is_drained_after_poll(self):
        self.log.write_text("iteration #1\n", encoding="utf-8")

        def exited():
            with self.log.open("a", encoding="utf-8") as fout:
                fout.write("estimated scf accuracy < 1e-9 Ry\nconvergence has been achieved\nJOB DONE.")
            self.proc.poll.return_value = 0
            self.proc.poll.side_effect = None
            return 0

        self.proc.poll.side_effect = exited
        with patch("scfopt.process_monitor.time.sleep"):
            result = self.monitor.run()
        self.assertTrue(result["success"])
        self.assertEqual(result["steps"], 1)

    def test_natural_job_requires_successful_exit_and_complete_convergence(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        with patch("scfopt.process_monitor.time.sleep"):
            for name, code, expected in (("si-converged", 0, "success"), ("si-converged", 1, "error"),
                                         ("si-maxstep", 0, "maxstep")):
                with self.subTest(name=name, code=code):
                    self.proc.returncode = self.proc.poll.return_value = code
                    self.log.write_bytes((examples / f"{name}.out").read_bytes())
                    monitor = ProcessMonitor(Mock(), self.proc, self.log, self.root, "si",
                                             GuardCfg(), GuardState(), 60, True)
                    result = monitor.run()
                    self.assertEqual(result["stop_reason"], expected)
                    self.assertEqual(result["returncode"], code)
                    self.assertEqual(result["success"], expected == "success")

    def test_fatal_or_rebound_disqualifies_intentional_stop(self):
        self.monitor.cfg.near_confirm_tail = 0
        self.monitor.stop_reason = "near_target_done"
        self.monitor.terminated_by_monitor = True
        self.proc.returncode = -15
        self.monitor.residuals = [1e-5]
        self.log.write_text("iteration #1\nestimated scf accuracy < 1e-5 Ry")
        self.assertEqual(self.monitor._final_result(1)["stop_reason"], "near_target_done")
        self.monitor.residuals.append(0.1)
        self.assertEqual(self.monitor._final_result(1)["stop_reason"], "error")
        self.monitor.residuals.pop()
        self.log.write_text("Program PWSCF v.7.5\nError in routine readpp (1)")
        self.assertEqual(self.monitor._final_result(1)["stop_reason"], "error")

    def test_failure_after_crossing_threshold_cannot_be_ranked(self):
        for stop in ("error", "diverge", "timeout", "maxstep", "neg_rho_excess", "oscillation_persistent", "stall"):
            with self.subTest(stop=stop):
                res = {"residuals": [1e-3, 1e-5, 0.1], "steps": 3, "stop_reason": stop, "time_s": 1,
                       "returncode": 1, "output_status": "incomplete", "job_dir": str(self.root),
                       "prefix_save": str(self.root / "missing.save")}
                record = probe_record(0.3, "PRE", res, {}, self.root, "si")
                self.assertEqual(record["S4"], 2)
                self.assertFalse(record["ok"])

    def test_negative_rho_guard_counts_reports_in_same_chunk(self):
        self.monitor.cfg.neg_rho_patience = 2
        self.monitor._consume_lines(["negative rho (up, down): 0.30 0.0"] * 2)
        self.assertEqual(self.monitor.stop_reason, "neg_rho_excess")

    def test_invalid_or_zero_printed_accuracy(self):
        self.monitor._consume_lines(["estimated scf accuracy < 0.00000000 Ry"])
        self.assertEqual(compute_s4(self.monitor.residuals, 1e-4), 1)
        self.monitor._consume_lines(["estimated scf accuracy < NaN Ry"])
        self.assertEqual(self.monitor.stop_reason, "error")

    def test_unavailable_seed_and_failed_verification(self):
        with patch("scfopt.workflow.clone_save_light") as copy:
            self.assertFalse(maybe_clone_seed({"seed_dir": ""}, {"inherit_seed": True}, self.root, "si"))
            self.assertFalse(maybe_clone_seed({"seed_dir": str(self.root)}, {"inherit_seed": True}, self.root, "si"))
            copy.assert_not_called()
        champion = {"beta": 0.3}
        rec = build_recommendation(Namespace(system="si"), {}, "si.in", champion, {"success": False},
                                   self.root / "summary.csv", self.root, 1)
        self.assertIsNone(rec["recommended_beta"])
        self.assertEqual(rec["recommendation_status"], "verification_failed")
        self.assertEqual(rec["champion_probe"], champion)
        self.assertEqual(rec["outdir"], str(self.root))

    def test_existing_results_and_concurrent_invocations_get_separate_directories(self):
        summary = self.root / "summary.csv"
        summary.write_text("previous results\n")
        self.assertEqual(reserve_output_dir(self.root).parent, self.root)
        self.assertEqual(summary.read_text(), "previous results\n")

        fresh = self.root / "shared"
        barrier = Barrier(4)

        def reserve(_):
            barrier.wait(timeout=5)
            return reserve_output_dir(fresh)

        with ThreadPoolExecutor(max_workers=4) as pool:
            directories = list(pool.map(reserve, range(4)))
        self.assertEqual(len(set(directories)), 4)
        self.assertIn(fresh, directories)
        for directory in directories:
            self.assertTrue((directory / "events.jsonl").is_file())
            self.assertTrue(directory == fresh or directory.parent == fresh)
