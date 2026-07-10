from __future__ import annotations

import subprocess as sp
from typing import Any, Iterable

import psutil


def _alive(processes: Iterable[psutil.Process]) -> list[psutil.Process]:
    out: list[psutil.Process] = []
    for process in processes:
        try:
            if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                out.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    return out


def terminate_process_tree(proc: sp.Popen[Any], grace_s: float = 0.75) -> None:
    """Terminate the owned Popen child and captured descendants without killpg."""
    if proc.poll() is not None:
        return
    try:
        descendants = psutil.Process(proc.pid).children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        descendants = []
    for child in reversed(_alive(descendants)):
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    try:
        proc.terminate()
    except (ProcessLookupError, OSError):
        return
    timeout = max(0.05, float(grace_s))
    alive = _alive(descendants)
    if alive:
        _, alive = psutil.wait_procs(alive, timeout=timeout)
    try:
        proc.wait(timeout=timeout)
    except sp.TimeoutExpired:
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
    except (ProcessLookupError, OSError):
        pass
    for child in _alive(alive):
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    remaining = _alive(alive)
    if remaining:
        psutil.wait_procs(remaining, timeout=timeout)
    try:
        proc.wait(timeout=timeout)
    except Exception:
        pass
