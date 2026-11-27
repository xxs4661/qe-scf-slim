from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _paths import ROOT
from parser import parse_scf_output


class ParserTests(unittest.TestCase):
    def test_parse_scf_output_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scf.out"
            path.write_text(
                """
iteration # 1
estimated scf accuracy < 2.0D-04 Ry
iteration # 2
estimated scf accuracy < 8.0D-06 Ry
!    total energy              =     -42.125000 Ry
convergence has been achieved
PWSCF        :   cpu 1.0s wall 2.5s
JOB DONE.
""",
                encoding="utf-8",
            )
            out = parse_scf_output(str(path))
        self.assertTrue(out["success"])
        self.assertFalse(out["error"])
        self.assertEqual(out["steps"], 2)
        self.assertEqual(out["residual"], 8.0e-6)
        self.assertEqual(out["energy"], -42.125)
        self.assertEqual(out["time"], 2.5)

    def test_truncated_append_cannot_inherit_a_previous_success(self) -> None:
        finished = (ROOT / "examples" / "si-converged.out").read_text()
        partial = finished.split("     iteration #  2")[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "appended.out"
            path.write_text(finished + partial, encoding="utf-8")
            out = parse_scf_output(str(path))
        self.assertEqual(out, {
            "success": False, "error": False, "no_convergence": True,
            "residual": 0.05941052, "steps": 1, "time": None, "energy": None,
        })

    def test_real_qe_footer_and_electronic_outcome_are_distinct(self) -> None:
        path = ROOT / "examples" / "si-maxstep.out"
        out = parse_scf_output(str(path))
        self.assertFalse(out["success"])
        self.assertTrue(out["no_convergence"])
        self.assertFalse(out["error"])
        self.assertGreater(out["time"], 0)

    def test_missing_output_is_error(self) -> None:
        out = parse_scf_output("/definitely/missing/scf.out")
        self.assertTrue(out["error"])
        self.assertFalse(out["success"])


if __name__ == "__main__":
    unittest.main()
