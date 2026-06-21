from __future__ import annotations

from pathlib import Path
from typing import List

from .utils import raw_logs, running_min_logs


def plot_residuals(path: Path, residuals: List[float], title: str) -> None:
    if not residuals:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        xs = list(range(1, len(residuals) + 1))
        raw = raw_logs(residuals)
        env = running_min_logs(residuals)
        plt.figure(figsize=(7, 4))
        plt.plot(xs[: len(raw)], raw, linewidth=1.0, label="raw")
        plt.plot(xs[: len(env)], env, linewidth=1.4, label="running min")
        plt.xlabel("SCF iteration")
        plt.ylabel("log10(residual Ry)")
        plt.title(title)
        plt.legend()
        plt.tight_layout()
        plt.savefig(path, dpi=180)
        plt.close()
    except Exception:
        pass

