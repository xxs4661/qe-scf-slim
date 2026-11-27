from __future__ import annotations

import argparse
import gzip
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from _paths import ROOT
from scfopt.triage import add_triage_parser


class TriageTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.good = ROOT / "examples" / "si-converged.out"
        self.maxstep = ROOT / "examples" / "si-maxstep.out"
        self.parser = argparse.ArgumentParser()
        add_triage_parser(self.parser.add_subparsers())

    def run_command(self, *args: str | Path) -> tuple[int, str]:
        parsed = self.parser.parse_args(["triage", *map(str, args)])
        output = io.StringIO()
        with redirect_stdout(output):
            result = parsed.handler(parsed)
        return result, output.getvalue()

    def test_directory_sorts_decisions_and_cites_latest_output(self) -> None:
        folder = self.root / "array"
        folder.mkdir()
        healthy = self.root / "00-healthy.out"
        healthy.write_bytes(self.good.read_bytes())
        running = folder / "a-running.out"
        running.write_text("     Program PWSCF v.7.5 starts on 27Nov2026\n     Self-consistent Calculation\n")
        failed = folder / "z-failed.out.gz"
        failed.write_bytes(gzip.compress(self.maxstep.read_bytes()))
        (folder / "ignore.in").write_text("input file")
        path_alias = folder / "linked.out"
        path_alias.symlink_to(healthy)
        (folder / "loop").symlink_to(self.root, target_is_directory=True)

        code, output = self.run_command("--json", self.root, failed)
        self.assertEqual(code, 0)
        data = json.loads(output)
        self.assertEqual(data["counts"], {"intervene": 1, "review": 1, "none": 1, "read_error": 0})
        self.assertEqual([row["path"] for row in data["runs"]], list(map(str, (failed, running, healthy))))
        reason = data["runs"][0]["intervention"]
        lines = self.maxstep.read_text().splitlines()
        self.assertTrue(any("convergence NOT achieved" in lines[n - 1] for n in reason["evidence_lines"]))
        self.assertTrue(reason["next_action"])

    def test_review_and_intervene_gate_and_healthy_output(self) -> None:
        partial = self.root / "running.out"
        partial.write_text("     Program PWSCF v.7.5 starts on 27Nov2026\n")
        self.assertEqual(self.run_command("--check", self.good)[0], 0)
        self.assertEqual(self.run_command("--check", partial)[0], 1)
        code, summary = self.run_command("--check", self.maxstep, self.good)
        self.assertEqual(code, 1)
        self.assertIn("[intervene]", summary)
        self.assertIn("none: 1", summary)
        self.assertNotIn(str(self.good), summary)
        self.assertIn("Source lines:", summary)
        self.assertIn("Next:", summary)

    def test_text_with_only_healthy_runs_shows_counts_until_all_requested(self) -> None:
        code, summary = self.run_command(self.good)
        self.assertEqual(code, 0)
        self.assertEqual(summary.splitlines(), ["intervene: 0  review: 0  read_error: 0  none: 1"])
        code, output = self.run_command("--all", self.maxstep, self.good)
        self.assertEqual(code, 0)
        self.assertLess(output.index("[intervene]"), output.index("[none]"))
        self.assertIn(str(self.good), output)
        for flags in (["--json"], ["--json", "--all"]):
            with self.subTest(flags=flags):
                _, text = self.run_command(*flags, self.good)
                self.assertEqual(json.loads(text)["runs"][0]["intervention"]["priority"], "none")

    def test_unreadable_and_empty_paths_keep_other_results(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        bad = self.root / "bad.gz"
        bad.write_bytes(b"not compressed")
        code, output = self.run_command("--check", "--json", empty, self.good, bad, self.maxstep)
        self.assertEqual(code, 2)
        data = json.loads(output)
        self.assertEqual(data["counts"]["read_error"], 2)
        self.assertEqual(data["counts"]["intervene"], 1)
        self.assertEqual(data["counts"]["none"], 1)
        errors = {row["path"]: row["error"] for row in data["runs"] if row["status"] == "read_error"}
        self.assertIn("no *.out", errors[str(empty)])
        self.assertIn(str(bad), errors)
        self.assertEqual(self.run_command(self.root / "missing.txt")[0], 2)

    def test_stdin_once_and_explicit_unusual_filename(self) -> None:
        unusual = self.root / "slurm-0009"
        unusual.write_bytes(self.maxstep.read_bytes())
        with patch("sys.stdin", io.StringIO(self.good.read_text())):
            code, output = self.run_command("--json", "-", unusual, "-")
        self.assertEqual(code, 0)
        rows = json.loads(output)["runs"]
        self.assertEqual([row["path"] for row in rows], [str(unusual), "-"])


if __name__ == "__main__":
    unittest.main()
