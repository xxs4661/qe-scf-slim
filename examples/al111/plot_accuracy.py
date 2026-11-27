"""Regenerate scf-accuracy.png from the two saved pw.x logs in this directory."""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Use the same iteration numbers, estimates and outcomes that triage reports.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts" / "scf_slim"))
from scfopt.diagnostics import diagnose


def plot_accuracy(high_beta_log: Path, low_beta_log: Path, destination: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.8, 4.6), layout="constrained")
    thresholds = set()
    for log, color, marker in ((high_beta_log, "#A84922", "o"), (low_beta_log, "#006E75", "s")):
        with log.open(encoding="utf-8") as stream:
            run = diagnose(stream)
        points = run["history"]
        steps = [point["iteration"] for point in points]
        accuracy = [point["residual_ry"] for point in points]
        outcome = "converged" if run["status"] == "converged" else "unconverged"
        label = f"β = {run['mixing_beta']:.2f}   {outcome} at step {run['iterations']}"
        ax.semilogy(steps, accuracy, color=color, marker=marker, markersize=4,
                    linewidth=1.6, markeredgewidth=0, label=label)
        thresholds.add(run["threshold_ry"])

    if len(thresholds) != 1 or None in thresholds:
        raise ValueError("The two logs must report the same SCF threshold.")
    threshold = thresholds.pop()
    ax.axhline(threshold, color="#505A66", linewidth=1.1, linestyle=(0, (5, 3)))
    ax.annotate("Requested threshold", (40, threshold), xytext=(0, 4), textcoords="offset points",
                ha="right", va="bottom", fontsize=9, color="#424D58")
    ax.set(xlim=(0, 41), ylim=(8e-10, 3e3), xticks=[1, 5, 10, 15, 20, 25, 30, 35, 40],
           yticks=[1e2, 1e0, 1e-2, 1e-4, 1e-6, 1e-8],
           xlabel="Electronic SCF iteration", ylabel="Estimated SCF accuracy (Ry)")
    ax.set_title("Six-layer Al(111) slab, two-vector mixing history", loc="left",
                 fontsize=15, fontweight="bold", pad=12)
    ax.minorticks_off()
    ax.grid(axis="y", color="#DEE2E6", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#68737E")
    ax.tick_params(color="#68737E", labelsize=10)
    ax.legend(loc="upper right", frameon=True, facecolor="white", edgecolor="none", framealpha=1, fontsize=10)
    fig.savefig(destination, dpi=175, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    plot_accuracy(HERE / "beta-070.out", HERE / "beta-020.out", HERE / "scf-accuracy.png")
