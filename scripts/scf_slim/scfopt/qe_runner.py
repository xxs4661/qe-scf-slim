from __future__ import annotations

import os
import shutil
import signal
import subprocess as sp
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .guards import GuardCfg, GuardState
from .process_monitor import ProcessMonitor
from .qe_input import render_qe_input


def sanitize_mixing_mode(mode: Optional[str]) -> Optional[str]:
    if not mode:
        return None
    normalized = str(mode).strip().lower().replace("_", "-")
    if normalized in ("broyden", "pulay"):
        return "plain"
    if normalized == "tf":
        return "TF"
    if normalized in ("local-tf", "localtf"):
        return "local-TF"
    if normalized == "plain":
        return "plain"
    return mode


class QERunner:
    def __init__(
        self,
        mpirun: Optional[str],
        pw: str,
        np: int = 1,
        extra_args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.mpirun = mpirun
        self.pw = pw
        self.np = int(np)
        self.extra_args = list(extra_args or [])
        self.env = os.environ.copy()
        self.env.update(env or {})

    def _build_cmd(self, infile: Path) -> List[str]:
        inarg = Path(infile).name
        pw_cmd = [self.pw, *self.extra_args, "-in", inarg]
        if self.mpirun:
            mpi_count_flag = "-n" if Path(self.mpirun).name.lower() == "srun" else "-np"
            return [self.mpirun, mpi_count_flag, str(self.np), *pw_cmd]
        return pw_cmd

    def _terminate_tree(self, proc: sp.Popen) -> None:
        try:
            if proc.poll() is None:
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGTERM)
                    time.sleep(0.5)
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
        except Exception:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass

    def run(
        self,
        template_text: str,
        *,
        outdir: Path,
        prefix: str,
        mixing_beta: float,
        degauss: Optional[float],
        conv_thr: float,
        electron_maxstep: int,
        mixing_mode: Optional[str] = None,
        wf_collect: bool = False,
        disk_io: str = "low",
        startingpot: Optional[str] = None,
        startingwfc: Optional[str] = None,
        restart_mode: Optional[str] = None,
        guard_cfg_dict: Optional[Dict[str, Any]] = None,
        episode_timeout_s: float = 7200.0,
        disable_guard: bool = False,
    ) -> Dict[str, Any]:
        job_dir = Path(outdir) / prefix
        job_dir.mkdir(parents=True, exist_ok=True)
        infile = job_dir / "scf.in"
        outfile = job_dir / "scf.out"
        prefix_save = job_dir / f"{prefix}.save"

        infile.write_text(self._render_input(template_text, job_dir, prefix, mixing_beta, degauss, conv_thr, electron_maxstep, mixing_mode, wf_collect, disk_io, startingpot, startingwfc, restart_mode), encoding="utf-8")

        with open(outfile, "wb") as fout:
            proc = sp.Popen(self._build_cmd(infile), cwd=str(job_dir), stdout=fout, stderr=sp.STDOUT, env=self.env, start_new_session=True)

        cfg = build_guard_cfg(guard_cfg_dict or {}, episode_timeout_s)
        state = GuardState(last_big_impr_step=min(cfg.burnin_steps, 10))
        monitor = ProcessMonitor(self._terminate_tree, proc, outfile, job_dir, prefix, cfg, state, electron_maxstep, disable_guard)
        result = monitor.run()
        result.update({"stdout_path": str(outfile), "prefix_save": str(prefix_save), "job_dir": str(job_dir)})
        return result

    def _render_input(
        self,
        template_text: str,
        job_dir: Path,
        prefix: str,
        mixing_beta: float,
        degauss: Optional[float],
        conv_thr: float,
        electron_maxstep: int,
        mixing_mode: Optional[str],
        wf_collect: bool,
        disk_io: str,
        startingpot: Optional[str],
        startingwfc: Optional[str],
        restart_mode: Optional[str],
    ) -> str:
        control = {
            "calculation": "scf",
            "prefix": prefix,
            "outdir": str(job_dir.resolve()),
            "wf_collect": wf_collect,
            "disk_io": disk_io,
            "verbosity": "low",
        }
        if self.env.get("ESPRESSO_PSEUDO"):
            control["pseudo_dir"] = self.env["ESPRESSO_PSEUDO"]
        if restart_mode:
            control["restart_mode"] = restart_mode

        system: Dict[str, Any] = {}
        if degauss is not None:
            system["degauss"] = degauss

        electrons = {"mixing_beta": mixing_beta, "conv_thr": conv_thr, "electron_maxstep": electron_maxstep}
        mode = sanitize_mixing_mode(mixing_mode)
        if mode:
            electrons["mixing_mode"] = mode
        if startingpot:
            electrons["startingpot"] = startingpot
        if startingwfc:
            electrons["startingwfc"] = startingwfc

        return render_qe_input(template_text, control, system, electrons)


def build_guard_cfg(values: Dict[str, Any], episode_timeout_s: float) -> GuardCfg:
    cfg = GuardCfg()
    for key, value in values.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    cfg.episode_timeout_s = float(episode_timeout_s)
    return cfg


HEAVY_PATTERNS = ("K", "wfc", "evc", "occup", "restart", "mix")


def cleanup_save_heavy(save_dir: Path) -> None:
    save_dir = Path(save_dir)
    if not save_dir.exists():
        return
    for root, dirs, files in os.walk(save_dir):
        for name in list(dirs) + list(files):
            if any(name.lower().startswith(pattern.lower()) for pattern in HEAVY_PATTERNS):
                path = Path(root) / name
                try:
                    shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
                except Exception:
                    pass


def cleanup_job_root_heavy(job_dir: Path) -> None:
    job_dir = Path(job_dir)
    if not job_dir.exists():
        return
    for path in job_dir.iterdir():
        if path.is_file() and any(pattern.lower() in path.name.lower() for pattern in HEAVY_PATTERNS):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def clone_save_light(src_save: Path, dst_save: Path) -> None:
    src_save = Path(src_save)
    dst_save = Path(dst_save)
    if not src_save.exists():
        return
    dst_save.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src_save):
        rel = Path(root).relative_to(src_save)
        dirs[:] = [d for d in dirs if not any(d.lower().startswith(p.lower()) for p in HEAVY_PATTERNS)]
        for filename in files:
            if any(filename.lower().startswith(p.lower()) for p in HEAVY_PATTERNS):
                continue
            src = Path(root) / filename
            dst = dst_save / rel / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass
