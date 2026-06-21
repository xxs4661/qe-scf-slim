from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .utils import ensure_dir


class EventLogger:
    def __init__(self, out_dir: Path, quiet: bool = False) -> None:
        self.out_dir = Path(out_dir)
        ensure_dir(self.out_dir)
        self.quiet = quiet
        self.text_path = self.out_dir / "console.log"
        self.jsonl_path = self.out_dir / "events.jsonl"

    def print(self, message: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        if not self.quiet:
            print(line, flush=True)
        with open(self.text_path, "a", encoding="utf-8") as fout:
            fout.write(line + "\n")

    def log(self, event: str, **payload: Any) -> None:
        record = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event}
        record.update(payload)
        with open(self.jsonl_path, "a", encoding="utf-8") as fout:
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")

