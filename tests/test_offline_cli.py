from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT, SCF_SLIM


class OfflineCliTests(unittest.TestCase):
    def cli(self, *args, source=None):
        # -S hides all site packages, including YAML and Matplotlib.
        return subprocess.run(
            [sys.executable, "-S", str(SCF_SLIM / "run_scf.py"), *args],
            input=source, text=True, capture_output=True,
        )

    def test_json_from_stdin_cites_actual_file_lines(self):
        lines = (ROOT / "examples" / "si-converged.out").read_text().splitlines()
        result = self.cli("diagnose", "-", "--check", "--json", source="\n".join(lines))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "converged")
        self.assertEqual(report["iterations"], 10)
        self.assertEqual(len(report["history"]), 10)
        for event in report["evidence"]:
            self.assertEqual(event["text"], lines[event["line"] - 1].strip())

    def test_gzip_report_and_opt_in_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Si.out.gz"
            path.write_bytes(gzip.compress((ROOT / "examples" / "si-maxstep.out").read_bytes()))
            result = self.cli("diagnose", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("convergence NOT achieved", result.stdout)
            self.assertEqual(self.cli("diagnose", "--check", str(path)).returncode, 1)

    def test_corrupt_gzip_is_a_structured_read_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.gz"
            path.write_bytes(b"invalid")
            result = self.cli("diagnose", "--json", str(path))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["status"], "read_error")

    def test_probe_dry_run_keeps_template_settings_and_resolves_relative_pseudos(self):
        template = ROOT / "examples" / "si-converged.in"
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env.pop("ESPRESSO_PSEUDO", None)
            result = subprocess.run(
                [sys.executable, str(SCF_SLIM / "run_scf.py"), "probe", "--template", str(template),
                 "--outdir", str(Path(tmp) / "runs"), "--dry-run"], env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["system"], template.stem)
            self.assertEqual(plan["effective_config"]["qe"]["env"]["ESPRESSO_PSEUDO"], str(template.parent / "pseudos"))
            self.assertIsNone(plan["effective_config"]["task"]["fixed_degauss"])
            self.assertIsNone(plan["effective_config"]["task"]["mixing_mode"])
            self.assertFalse((Path(tmp) / "runs").exists())

    def test_unreadable_benchmark_and_malformed_yaml_have_actionable_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "invalid.yml"
            config.write_text("task: [")
            for argv in (["--doctor", "--config", str(config)], ["--list-systems", "--bench", str(config) + ".missing"]):
                result = subprocess.run([sys.executable, str(SCF_SLIM / "run_scf.py"), *argv], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Probe failed", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
