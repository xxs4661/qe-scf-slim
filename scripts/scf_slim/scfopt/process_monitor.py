from __future__ import annotations

import os
import subprocess as sp
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .diagnostics import diagnose
from .guards import GuardCfg, GuardState, NEG_RHO_ANY, guard_evaluate_step, near_target_stop, parse_new_lines


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
        self._partial = b""
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
        self.terminated_by_monitor = False

    def run(self) -> Dict[str, Any]:
        last_size = 0
        start = time.monotonic()
        try:
            while True:
                time.sleep(0.5)
                wall = time.monotonic() - start
                last_size = self._read_new_output(last_size)
                if self.proc.poll() is not None:
                    break
                if self._should_stop_from_timeout(wall) or self._should_stop_from_guard(wall):
                    break
        finally:
            if self.proc.poll() is None:
                self.terminated_by_monitor = True
                self.terminate_proc(self.proc)
            try:
                self.proc.wait(timeout=5)
            except sp.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        # poll() can observe exit after the last read. Drain the remaining bytes,
        # including an unterminated last line, before interpreting the result.
        self._read_new_output(last_size, final=True)
        return self._final_result(time.monotonic() - start)

    def _read_new_output(self, last_size: int, final: bool = False) -> int:
        try:
            with self.outfile.open("rb") as fin:
                fin.seek(last_size)
                data = self._partial + fin.read()
                offset = fin.tell()
        except FileNotFoundError:
            return last_size
        if final:
            self._partial = b""
        else:
            data, _, self._partial = data.rpartition(b"\n")
        self._consume_lines(data.decode("utf-8", errors="replace").splitlines())
        return offset

    def _consume_lines(self, lines: List[str]) -> None:
        for line in lines:
            added, energy, succeeded, neg_vals, nelec = parse_new_lines([line], self.residuals)
            if not added and line.lstrip().lower().startswith("estimated scf accuracy"):
                self.stop_reason = "error"
                self.stop_detail = {"invalid_accuracy": line.strip()}
            if energy is not None:
                self.energy = energy
            self.success_flag |= succeeded
            if nelec is not None:
                self.nelec = nelec
            if not self.disable_guard and self.cfg.neg_rho_guard_enabled and NEG_RHO_ANY.search(line):
                self._update_negative_rho(neg_vals)

    def _update_negative_rho(self, neg_vals: Optional[tuple[float, float]]) -> None:
        if neg_vals is None:
            if self.cfg.neg_rho_unknown_fatal:
                self.stop_reason = "neg_rho_excess"
                self.stop_detail = {"unknown": True}
            return
        total_neg = max(0.0, (neg_vals[0] or 0.0) + (neg_vals[1] or 0.0))
        self.neg_rho_last = total_neg
        self.neg_rho_max = max(self.neg_rho_max, total_neg)
        allow = float(self.cfg.neg_rho_abs_tol)
        if self.nelec is not None and float(self.cfg.neg_rho_rel_tol) > 0:
            allow = max(allow, float(self.cfg.neg_rho_rel_tol) * float(self.nelec))
        self.neg_over_count = self.neg_over_count + 1 if total_neg > allow else 0
        if self.neg_over_count >= int(self.cfg.neg_rho_patience):
            self.stop_reason = "neg_rho_excess"
            self.stop_detail = {
                "neg_rho_last": self.neg_rho_last,
                "neg_rho_max": self.neg_rho_max,
                "neg_rho_over_count": self.neg_over_count,
                "nelec": self.nelec,
            }

    def _should_stop_from_guard(self, wall: float) -> bool:
        if self.stop_reason:
            return True
        if not self.residuals or self.disable_guard or self.exit_requested or self.success_flag:
            return False
        reason, detail = guard_evaluate_step(self.residuals, len(self.residuals), wall, self.electron_maxstep, self.cfg, self.state)
        if reason is None:
            return False
        if reason == "near_target_done" and self.cfg.near_graceful_exit:
            self._request_exit(reason, detail or {})
            return bool(self.stop_reason)
        self.stop_reason = reason
        self.stop_detail = detail or {}
        return True

    def _request_exit(self, reason: str, detail: Dict[str, Any]) -> None:
        try:
            (self.job_dir / f"{self.prefix}.EXIT").write_text("EXIT\n", encoding="utf-8")
            self.exit_requested = True
            self.exit_request_time = time.monotonic()
            self.exit_reason = reason
            self.exit_detail = detail
        except OSError:
            self.stop_reason = reason
            self.stop_detail = detail

    def _should_stop_from_timeout(self, wall: float) -> bool:
        if wall >= self.cfg.episode_timeout_s:
            self.stop_reason = "timeout"
            self.stop_detail = {"wall_s": wall}
            return True
        if self.exit_request_time is not None and time.monotonic() - self.exit_request_time >= self.cfg.near_grace_wait_s:
            self.stop_reason = "timeout"
            self.stop_detail = {"exit_timeout": True, "wall_s": wall}
            return True
        return False

    def _final_result(self, wall: float) -> Dict[str, Any]:
        with self.outfile.open(encoding="utf-8", errors="replace") as stream:
            report = diagnose(stream)
        status = report["status"]
        returncode = self.proc.returncode
        reason = self.stop_reason or self.exit_reason
        detail = self.stop_detail if self.stop_reason else self.exit_detail
        if reason == "near_target_done":
            # A requested hard probe stop often exits on SIGTERM/SIGKILL. A
            # graceful EXIT request must let the solver finish on its own.
            expected_kill_codes = {1} if os.name == "nt" else {-15, -9, 143, 137}
            intentional_signal = self.terminated_by_monitor and returncode in expected_kill_codes
            confirmed = near_target_stop(self.residuals, len(self.residuals), self.cfg)
            if not confirmed or status in ("failed", "unsupported", "unconverged") or (returncode != 0 and not intentional_signal):
                reason = "error"
        elif reason is None:
            if status == "converged" and returncode == 0:
                reason = "success"
            elif status == "unconverged":
                reason = "maxstep"
            else:
                reason = "error"
        return {
            "success": reason == "success",
            "stop_reason": reason,
            "returncode": returncode,
            "output_status": status,
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
