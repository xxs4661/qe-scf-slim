"""Replay the measured beta pair, the reverse-order repeat and the history controls."""

import hashlib
import json
import unittest
from zipfile import ZipFile

from _paths import ROOT
from scfopt.diagnostics import diagnose


CASE = ROOT / "examples" / "al111"


class Al111ValidationTests(unittest.TestCase):
    def test_matching_primary_inputs_differ_only_in_beta(self):
        high = (CASE / "beta-070.in").read_text()
        low = (CASE / "beta-020.in").read_text()
        self.assertEqual(high.count("mixing_beta=0.70"), 1)
        self.assertEqual(high.replace("mixing_beta=0.70", "mixing_beta=0.20"), low)

    def test_decisions_on_all_six_real_runs(self):
        measurements = json.loads((CASE / "measurements.json").read_text())
        self.assertEqual(len(measurements["runs"]), 6)
        with ZipFile(CASE / measurements["validation_archive"]) as archive:
            for run in measurements["runs"]:
                with self.subTest(order=run["run_order"]):
                    if "included_stdout" in run:
                        source = (CASE / run["included_stdout"]).read_bytes()
                    else:
                        source = archive.read(run["archived_stdout"])
                    self.assertEqual(hashlib.sha256(source).hexdigest(), run["stdout_sha256"])
                    lines = source.decode().splitlines()
                    report = diagnose(lines)
                    self.assertEqual(report["status"], run["status"])
                    self.assertEqual(report["iterations"], run["iterations"])
                    self.assertEqual(report["residual_ry"], run["last_printed_accuracy_ry"])
                    self.assertEqual(report["mixing_beta"], run["mixing_beta"])
                    self.assertTrue(report["job_done"])
                    decision = report["intervention"]
                    unstable = run["mixing_ndim"] == 2 and run["mixing_beta"] == 0.70
                    expected = ("intervene", "repeated_rebounds") if unstable else ("none", "converged")
                    self.assertEqual((decision["priority"], decision["code"]), expected)
                    cited = {event["line"]: event["text"] for event in report["evidence"]}
                    for n in decision["evidence_lines"]:
                        self.assertEqual(cited[n], lines[n - 1].strip())

    def test_partial_output_cannot_justify_stopping_a_running_job(self):
        lines = (CASE / "beta-070.out").read_text().splitlines()
        first_13 = diagnose(lines)["history"][12]
        self.assertEqual(first_13["iteration"], 13)
        snapshot = diagnose(lines[:first_13["line"]])
        self.assertFalse(snapshot["job_done"])
        action = snapshot["intervention"]
        self.assertEqual((action["priority"], action["code"]), ("review", "monitor_rebounds"))
        self.assertLessEqual(max(action["evidence_lines"]), first_13["line"])
