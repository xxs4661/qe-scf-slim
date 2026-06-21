from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List


SUMMARY_FIELDS = [
    "beta",
    "ok",
    "S4",
    "steps",
    "stop",
    "time_s",
    "energy",
    "b_abs",
    "R2",
    "fit_n",
    "M_after_S4",
    "osc_hits",
    "neg_rho_max",
    "stage",
    "seed_dir",
    "stdout_path",
    "job_dir",
]


def write_summary(out_dir: Path, records: List[Dict[str, Any]]) -> Path:
    path = out_dir / "summary.csv"
    with open(path, "w", newline="", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for record in sorted(records, key=lambda item: float(item["beta"])):
            writer.writerow({field: record.get(field) for field in SUMMARY_FIELDS})
    return path

