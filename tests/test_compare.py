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
from scfopt.compare import add_compare_parser


class CompareTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.good = ROOT / "examples" / "si-converged.out"
        self.maxstep = ROOT / "examples" / "si-maxstep.out"
        self.live = self.root / "running.out"
        self.live.write_text(self.good.read_text().split("     iteration #  2")[0])
        self.parser = argparse.ArgumentParser()
        add_compare_parser(self.parser.add_subparsers())

    def compare(self, *args: str | Path) -> tuple[int, str]:
        parsed = self.parser.parse_args(["compare", *map(str, args)])
        output = io.StringIO()
        with redirect_stdout(output):
            code = parsed.handler(parsed)
        return code, output.getvalue()

    def test_batch_json_preserves_order_units_and_outcomes(self) -> None:
        code, text = self.compare(self.live, self.good, "--json")
        data = json.loads(text)
        self.assertEqual(code, 0)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["counts"], {"incomplete": 1, "converged": 1})
        self.assertEqual([row["path"] for row in data["runs"]], [str(self.live), str(self.good)])
        finished = data["runs"][1]
        self.assertEqual(finished["iterations"], 10)
        self.assertEqual(finished["mixing_beta"], 0.5)
        self.assertAlmostEqual(finished["residual_ry"], 4.7e-9, delta=1e-11)
        self.assertEqual(finished["residual_operator"], "<")
        self.assertEqual(finished["threshold_ry"], 1e-8)
        self.assertGreater(finished["wall_seconds"], 0)

    def test_check_gate_follows_run_status(self) -> None:
        self.assertEqual(self.compare("--check", self.good)[0], 0)
        self.assertEqual(self.compare("--check", self.good, self.live)[0], 1)
        code, text = self.compare("--check", "--json", self.good, self.maxstep)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(text)["runs"][1]["status"], "unconverged")

    def test_repeated_stdin_is_reported_without_discarding_other_results(self) -> None:
        with patch("sys.stdin", io.StringIO(self.good.read_text())):
            code, output = self.compare("--json", "-", "-", self.maxstep)
        self.assertEqual(code, 2)
        self.assertEqual(
            [row["status"] for row in json.loads(output)["runs"]],
            ["converged", "read_error", "unconverged"],
        )

    def test_read_errors_keep_successful_rows_and_take_precedence(self) -> None:
        missing = self.root / "missing.out"
        corrupt = self.root / "truncated.out.gz"
        corrupt.write_bytes(gzip.compress(self.good.read_bytes())[:-4])
        code, text = self.compare("--json", "--check", missing, self.live, corrupt, self.good)
        self.assertEqual(code, 2)
        rows = json.loads(text)["runs"]
        self.assertEqual(
            [row["status"] for row in rows],
            ["read_error", "incomplete", "read_error", "converged"],
        )
        self.assertTrue(rows[0]["error"])
        self.assertTrue(rows[2]["error"])
        self.assertEqual(self.compare(missing)[0], 2)

    def test_table_shows_printed_accuracy_bound_and_paths_in_order(self) -> None:
        code, output = self.compare(self.live, self.good)
        self.assertEqual(code, 0)
        self.assertIn("Est. acc. (Ry)", output)
        self.assertIn("<4.7e-09", output)
        self.assertLess(output.index(str(self.live)), output.index(str(self.good)))
        self.assertIn("1 converged", output)
        self.assertIn("1 incomplete", output)


if __name__ == "__main__":
    unittest.main()
