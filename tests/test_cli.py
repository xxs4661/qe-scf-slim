from __future__ import annotations

import json
import subprocess
import sys
import unittest

from _paths import SCF_SLIM


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "run_scf.py", *args],
            cwd=SCF_SLIM,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_list_systems_from_benchmark(self) -> None:
        proc = self.run_cli("--bench", "configs/benchmark.yaml", "--list-systems")
        systems = set(proc.stdout.splitlines())
        self.assertIn("BaTiO3", systems)
        self.assertIn("Fe_bcc", systems)

    def test_doctor_json_no_run_check_is_machine_readable(self) -> None:
        proc = self.run_cli(
            "--doctor",
            "--doctor-json",
            "--doctor-no-run-check",
            "--config",
            "configs/default.yaml",
        )
        report = json.loads(proc.stdout)
        self.assertIn("status", report)
        self.assertIn("recommendation", report)
        self.assertIn("qe", report["recommendation"])


if __name__ == "__main__":
    unittest.main()
