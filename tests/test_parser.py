from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _paths import SCF_SLIM  # noqa: F401
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

    def test_missing_output_is_error(self) -> None:
        out = parse_scf_output("/definitely/missing/scf.out")
        self.assertTrue(out["error"])
        self.assertFalse(out["success"])


if __name__ == "__main__":
    unittest.main()
