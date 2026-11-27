"""Read a plain or gzip-compressed pw.x log, or the caller's standard input."""

import gzip
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import ContextManager, TextIO


def open_log(path: str) -> ContextManager[TextIO]:
    if path == "-":
        return nullcontext(sys.stdin)
    if Path(path).suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")
