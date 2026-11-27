from __future__ import annotations

import unittest

from _paths import SCF_SLIM  # noqa: F401
from scfopt.qe_input import render_qe_input, template_pseudo_dir


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


    def test_compact_namelists_preserve_physics_quotes_and_cards(self) -> None:
        template = """&control title="mixing_beta=1 ! /", prefix='it''s/old', pseudo_dir='./upf' /
&system ecutwfc=40, ecutrho=320, occupations='smearing', degauss=0.01 /
&electrons mixing_beta=0.7, mixing_ndim=12 ! mixing_beta=9 /
 conv_thr=1.0d-6 /
K_POINTS gamma
"""
        self.assertEqual(template_pseudo_dir(template), "./upf")
        rendered = render_qe_input(template, {"prefix": "it's/new"}, {}, {"mixing_beta": 0.3})
        self.assertIn("prefix = 'it''s/new'", rendered)
        self.assertIn('title="mixing_beta=1 ! /"', rendered)
        self.assertIn("mixing_beta = 0.3, mixing_ndim=12", rendered)
        self.assertIn("! mixing_beta=9 /", rendered)
        self.assertIn("ecutrho=320, occupations='smearing', degauss=0.01", rendered)
        self.assertTrue(rendered.endswith("K_POINTS gamma\n"))

    def test_missing_electrons_namelist_is_inserted_before_cards(self) -> None:
        template = "&CONTROL /\n&SYSTEM nat=2 /\nATOMIC_SPECIES\nSi 28 Si.UPF\n"
        output = render_qe_input(template, {}, {}, {"mixing_beta": 0.5})
        self.assertLess(output.index("&SYSTEM"), output.index("&ELECTRONS"))
        self.assertLess(output.index("&ELECTRONS"), output.index("ATOMIC_SPECIES"))


if __name__ == "__main__":
    unittest.main()
