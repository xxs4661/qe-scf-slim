from __future__ import annotations

import unittest

from _paths import SCF_SLIM  # noqa: F401
from scfopt.qe_input import render_qe_input


class QeInputTests(unittest.TestCase):
    def test_render_qe_input_replaces_existing_values(self) -> None:
        template = """
systems:
  - ignored yaml wrapper
&control
  prefix='old'
/
&system
  ecutwfc=30
/
&electrons
  mixing_beta=0.70
/
ATOMIC_SPECIES
H 1.0 H.UPF
"""
        rendered = render_qe_input(
            template,
            control={"prefix": "new", "outdir": "/tmp/scf"},
            system={"ecutwfc": 50},
            electrons={"mixing_beta": 0.3, "conv_thr": 1e-8},
        )
        self.assertTrue(rendered.startswith("&CONTROL"))
        self.assertIn("prefix = 'new'", rendered)
        self.assertIn("outdir = '/tmp/scf'", rendered)
        self.assertIn("ecutwfc = 50", rendered)
        self.assertIn("mixing_beta = 0.3", rendered)
        self.assertIn("conv_thr = 1e-08", rendered)
        self.assertNotIn("prefix='old'", rendered)
        self.assertEqual(rendered.count("mixing_beta"), 1)


if __name__ == "__main__":
    unittest.main()
