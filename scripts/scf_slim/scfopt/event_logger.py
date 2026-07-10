from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class EventLogger:
    def __init__(self, out_dir: Path, quiet: bool = False, append: bool = False) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.quiet = quiet
        self.console_path = self.out_dir / "console.log"
        self.jsonl_path = self.out_dir / "events.jsonl"
        if not append:
            self.console_path.write_text("", encoding="utf-8")
            self.jsonl_path.write_text("", encoding="utf-8")

    def print(self, message: str) -> None:
        line = str(message)
        with open(self.console_path, "a", encoding="utf-8") as fout:
            fout.write(line + "\n")
        if not self.quiet:
            print(line)

    def log(self, event: str, **payload: Any) -> None:
        record = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **payload}
        with open(self.jsonl_path, "a", encoding="utf-8") as fout:
            fout.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
