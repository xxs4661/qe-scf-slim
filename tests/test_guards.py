from __future__ import annotations

import unittest

from _paths import SCF_SLIM  # noqa: F401
from scfopt.guards import GuardCfg, GuardState, guard_evaluate_step, parse_new_lines


class GuardTests(unittest.TestCase):
    def test_near_target_stop_can_finish_probe(self) -> None:
        cfg = GuardCfg(target_residual_ry=1e-4, near_confirm_tail=0)
        reason, detail = guard_evaluate_step([1e-3, 8e-5], 2, 0.0, 100, cfg, GuardState())
        self.assertEqual(reason, "near_target_done")
        self.assertLess(detail["e_last"], 1e-4)

    def test_divergence_stop_detects_repeated_large_residuals(self) -> None:
        cfg = GuardCfg(
            burnin_steps=0,
            adaptive_triggers=False,
            diverge_start_after_steps=0,
            diverge_min_L=4,
            diverge_steps=3,
            diverge_ratio=3.5,
            target_residual_ry=1e-12,
        )
        residuals = [1.0, 0.5, 0.25, 0.1, 0.6, 0.7, 0.8]
        reason, detail = guard_evaluate_step(residuals, len(residuals), 0.0, 100, cfg, GuardState())
        self.assertEqual(reason, "diverge")
        self.assertEqual(detail["ratio"], 3.5)

    def test_parse_new_lines_reads_qe_markers(self) -> None:
        residuals: list[float] = []
        added, energy, success, neg_vals, nelec = parse_new_lines(
            [
                "estimated scf accuracy < 1.2D-05 Ry",
                "!    total energy              =     -10.500000 Ry",
                "convergence has been achieved",
                "negative rho (up, down): 1.0D-03 2.0D-03",
                "number of electrons = 8.0",
            ],
            residuals,
        )
        self.assertEqual(added, 1)
        self.assertEqual(residuals, [1.2e-5])
        self.assertEqual(energy, -10.5)
        self.assertTrue(success)
        self.assertEqual(neg_vals, (1.0e-3, 2.0e-3))
        self.assertEqual(nelec, 8.0)


if __name__ == "__main__":
    unittest.main()
