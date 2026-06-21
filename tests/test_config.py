from __future__ import annotations

import unittest

from _paths import SCF_SLIM
from scfopt.config import effective_config, list_systems, load_template


class ConfigTests(unittest.TestCase):
    def test_effective_config_order(self) -> None:
        cfg = effective_config(
            {
                "preset": "smoke",
                "search": {"max_evals": 99},
                "overrides": {
                    "search": {"max_evals": 9},
                    "task": {"electron_maxstep": 88},
                },
                "system_overrides": {
                    "Fe_bcc": {
                        "task": {"mixing_mode": "plain"},
                    }
                },
            },
            "Fe_bcc",
        )
        self.assertFalse(cfg["verify"]["enabled"])
        self.assertEqual(cfg["search"]["max_evals"], 9)
        self.assertEqual(cfg["task"]["electron_maxstep"], 88)
        self.assertEqual(cfg["task"]["mixing_mode"], "plain")

    def test_benchmark_templates_are_loadable(self) -> None:
        bench = SCF_SLIM / "configs" / "benchmark.yaml"
        systems = list_systems(bench)
        self.assertIn("Fe_bcc", systems)
        text, path = load_template(str(bench), None, "Fe_bcc")
        self.assertIn("&CONTROL", text)
        self.assertTrue(path.endswith("Fe_bcc_scf.in"))


if __name__ == "__main__":
    unittest.main()
