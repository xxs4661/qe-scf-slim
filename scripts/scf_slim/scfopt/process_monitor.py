from __future__ import annotations

import subprocess as sp
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .guards import GuardCfg, GuardState, NEG_RHO_ANY, guard_evaluate_step, parse_new_lines


TerminateProc = Callable[[sp.Popen], None]


class ProcessMonitor:
    def __init__(
        self,
        terminate_proc: TerminateProc,
        proc: sp.Popen,
        outfile: Path,
        job_dir: Path,
        prefix: str,
        cfg: GuardCfg,
        state: GuardState,
        electron_maxstep: int,
        disable_guard: bool,
    ) -> None:
        self.terminate_proc = terminate_proc
        self.proc = proc
        self.outfile = outfile
        self.job_dir = job_dir
        self.prefix = prefix
        self.cfg = cfg
        self.state = state
        self.electron_maxstep = int(electron_maxstep)
        self.disable_guard = disable_guard
        self.residuals: List[float] = []
        self.energy: Optional[float] = None
        self.success_flag = False
        self.stop_reason: Optional[str] = None
        self.stop_detail: Dict[str, Any] = {}
        self.nelec: Optional[float] = None
        self.neg_over_count = 0
        self.neg_rho_max = 0.0
        self.neg_rho_last: Optional[float] = None
        self.exit_requested = False
        self.exit_request_time: Optional[float] = None
        self.exit_reason: Optional[str] = None
        self.exit_detail: Dict[str, Any] = {}

    def run(self) -> Dict[str, Any]:
        last_size = 0
        start = time.time()
        try:
            while True:
                time.sleep(0.5)
                wall = time.time() - start
                last_size = self._read_new_output(last_size)
                if self._should_stop_from_guard(wall) or self._should_stop_from_timeout(wall):
                    break
                if self.proc.poll() is not None:
                    break
            try:
                self.proc.wait(timeout=5)
            except Exception:
                pass
        finally:
            try:
                if self.proc.poll() is None:
                    self.terminate_proc(self.proc)
            except Exception:
                pass
        return self._final_result(time.time() - start)

    def _read_new_output(self, last_size: int) -> int:
        try:
            size = self.outfile.stat().st_size
        except FileNotFoundError:
            return last_size
        if size == last_size:
            return last_size
        with open(self.outfile, "r", encoding="utf-8", errors="ignore") as fin:
            fin.seek(last_size)
            chunk = fin.read()
        self._consume_lines(chunk.splitlines())
        return size

    def _consume_lines(self, lines: List[str]) -> None:
        _, latest_e, succ, neg_vals, nelec_new = parse_new_lines(lines, self.residuals)
        if latest_e is not None:
            self.energy = latest_e
        if succ:
            self.success_flag = True
        if nelec_new is not None:
            self.nelec = nelec_new
        if self.cfg.neg_rho_guard_enabled and (neg_vals is not None or any(NEG_RHO_ANY.search(line) for line in lines)):
            self._update_negative_rho(neg_vals)

    def _update_negative_rho(self, neg_vals: Optional[tuple[float, float]]) -> None:
        if neg_vals is None:
            if self.cfg.neg_rho_unknown_fatal:
                self.stop_reason = "neg_rho_excess"
                self.stop_detail = {"unknown": True}
                self.terminate_proc(self.proc)
            return
        total_neg = max(0.0, (neg_vals[0] or 0.0) + (neg_vals[1] or 0.0))
        self.neg_rho_last = total_neg
        self.neg_rho_max = max(self.neg_rho_max, total_neg)
        allow = float(self.cfg.neg_rho_abs_tol)
        if self.nelec is not None and float(self.cfg.neg_rho_rel_tol) > 0:
            allow = max(allow, float(self.cfg.neg_rho_rel_tol) * float(self.nelec))
        self.neg_over_count = self.neg_over_count + 1 if total_neg > allow else 0

    def _should_stop_from_guard(self, wall: float) -> bool:
        if not self.residuals or self.disable_guard or self.exit_requested or self.stop_reason:
            return bool(self.stop_reason)
        if self.neg_over_count >= int(self.cfg.neg_rho_patience):
            self.stop_reason = "neg_rho_excess"
            self.stop_detail = {
                "neg_rho_last": self.neg_rho_last,
                "neg_rho_max": self.neg_rho_max,
                "neg_rho_over_count": self.neg_over_count,
                "nelec": self.nelec,
            }
            self.terminate_proc(self.proc)
            return True
        reason, detail = guard_evaluate_step(self.residuals, len(self.residuals), wall, self.electron_maxstep, self.cfg, self.state)
        if reason is None:
            return False
        if reason == "near_target_done" and self.cfg.near_graceful_exit:
            self._request_exit(reason, detail or {})
            return False
        self.stop_reason = reason
        self.stop_detail = detail or {}
        self.terminate_proc(self.proc)
        return True

    def _request_exit(self, reason: str, detail: Dict[str, Any]) -> None:
        try:
            (self.job_dir / f"{self.prefix}.EXIT").write_text("EXIT\n", encoding="utf-8")
            self.exit_requested = True
            self.exit_request_time = time.time()
            self.exit_reason = reason
            self.exit_detail = detail
        except Exception:
            self.stop_reason = reason
            self.stop_detail = detail
            self.terminate_proc(self.proc)

    def _should_stop_from_timeout(self, wall: float) -> bool:
        if self.exit_requested and self.proc.poll() is None and time.time() - (self.exit_request_time or time.time()) > float(self.cfg.near_grace_wait_s):
            self.stop_reason = self.exit_reason or "near_target_done"
            self.stop_detail = dict(self.exit_detail or {})
            self.stop_detail.setdefault("exit_timeout", True)
            self.terminate_proc(self.proc)
            return True
        if not self.exit_requested and wall >= self.cfg.episode_timeout_s:
            self.stop_reason = "timeout"
            self.stop_detail = {"wall_s": wall}
            self.terminate_proc(self.proc)
            return True
        return False

    def _final_result(self, wall: float) -> Dict[str, Any]:
        reason = self.stop_reason
        detail = self.stop_detail
        if reason is None:
            if self.exit_reason is not None:
                reason = self.exit_reason
                detail = self.exit_detail or {}
            elif self.success_flag:
                reason = "success"
            elif self.residuals and len(self.residuals) >= self.electron_maxstep:
                reason = "maxstep"
            else:
                reason = "error"
        return {
            "success": reason == "success",
            "stop_reason": reason,
            "stop_reason_detail": detail,
            "residuals": self.residuals,
            "steps": len(self.residuals),
            "energy": self.energy,
            "time_s": wall,
            "diagnostics": {
                "osc_transient_hits": self.state.osc_transient_hits,
                "neg_rho_last": self.neg_rho_last,
                "neg_rho_max": self.neg_rho_max,
                "neg_rho_over_count": self.neg_over_count,
                "nelec": self.nelec,
                "save_dir_exists_after_stop": (self.job_dir / f"{self.prefix}.save").exists(),
            },
        }
