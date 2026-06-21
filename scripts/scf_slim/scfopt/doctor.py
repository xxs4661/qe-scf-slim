from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess as sp
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml


def run_doctor(
    *,
    cfg: Optional[Dict[str, Any]] = None,
    cwd: Optional[Path] = None,
    search_roots: Optional[List[Path]] = None,
    explicit_pw: Optional[str] = None,
    explicit_mpirun: Optional[str] = None,
    explicit_pseudo_dir: Optional[str] = None,
    np: int = 1,
    run_checks: bool = True,
) -> Dict[str, Any]:
    cwd = Path(cwd or Path.cwd()).resolve()
    cfg = cfg or {}
    qe = cfg.get("qe", {}) if isinstance(cfg.get("qe", {}), dict) else {}
    env_cfg = qe.get("env", {}) if isinstance(qe.get("env", {}), dict) else {}
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in env_cfg.items() if v is not None})

    pw_candidates = discover_pw_candidates(cwd, cfg, search_roots, explicit_pw)
    mpi_candidates = discover_mpi_candidates(cfg, explicit_mpirun)
    pseudo_candidates = discover_pseudo_dirs(cwd, cfg, explicit_pseudo_dir)

    pw_checks = [check_pw(candidate, env, run_checks) for candidate in pw_candidates[:8]]
    mpi_checks = [check_mpi(candidate, env, run_checks) for candidate in mpi_candidates[:8]]

    selected_pw = select_first_ok(pw_checks) or (pw_checks[0] if pw_checks else None)
    direct_ok = bool(selected_pw and selected_pw.get("run_ok"))
    mpi_pw_check = None
    selected_mpi = None
    if selected_pw and not direct_ok:
        for mpi in mpi_checks:
            if not mpi.get("exists"):
                continue
            candidate = check_pw_with_mpi(selected_pw["path"], mpi["path"], env, np, run_checks)
            if selected_mpi is None:
                selected_mpi = mpi
                mpi_pw_check = candidate
            if candidate.get("run_ok"):
                mpi_pw_check = candidate
                selected_mpi = mpi
                break
    elif mpi_checks:
        selected_mpi = mpi_checks[0]

    selected_pseudo = select_pseudo_dir(pseudo_candidates)
    prefer_mpi = bool(explicit_mpirun or qe.get("mpirun") or int(np) > 1)
    recommendation = build_recommendation(selected_pw, selected_mpi, selected_pseudo, np, direct_ok, mpi_pw_check, env_cfg, prefer_mpi)
    status = classify_status(selected_pw, selected_mpi, selected_pseudo, direct_ok, mpi_pw_check)
    report = {
        "status": status,
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cwd": str(cwd),
        },
        "pw_candidates": pw_checks,
        "mpi_candidates": mpi_checks,
        "pseudo_candidates": pseudo_candidates,
        "mpi_pw_check": mpi_pw_check,
        "recommendation": recommendation,
        "notes": build_notes(status, selected_pw, selected_pseudo, direct_ok, mpi_pw_check, mpi_checks),
    }
    return report


def discover_pw_candidates(cwd: Path, cfg: Dict[str, Any], search_roots: Optional[List[Path]], explicit_pw: Optional[str]) -> List[str]:
    values: List[str] = []
    qe = cfg.get("qe", {}) if isinstance(cfg.get("qe", {}), dict) else {}
    add_path(values, explicit_pw)
    add_path(values, os.environ.get("PW_X"))
    cfg_pw = qe.get("pw")
    if cfg_pw and str(cfg_pw) != "pw.x":
        add_path(values, str(cfg_pw))
    add_path(values, shutil.which("pw.x"))
    qe_bin = os.environ.get("QE_BIN")
    if qe_bin:
        add_path(values, str(Path(qe_bin).expanduser() / "pw.x"))

    roots = [cwd, cwd.parent, Path.home()]
    roots.extend(search_roots or [])
    patterns = ("qe*/PW/src/pw.x", "q-e*/PW/src/pw.x", "espresso*/PW/src/pw.x", "qe*/bin/pw.x", "espresso*/bin/pw.x")
    for root in unique_paths(roots):
        if not root.exists() or not root.is_dir():
            continue
        for pattern in patterns:
            for path in sorted(root.glob(pattern))[:12]:
                add_path(values, str(path))
    for common in ("/usr/local/bin/pw.x", "/opt/homebrew/bin/pw.x", "/usr/bin/pw.x"):
        add_path(values, common)
    return unique_strings(values)


def discover_mpi_candidates(cfg: Dict[str, Any], explicit_mpirun: Optional[str]) -> List[str]:
    values: List[str] = []
    qe = cfg.get("qe", {}) if isinstance(cfg.get("qe", {}), dict) else {}
    add_path(values, explicit_mpirun)
    add_path(values, os.environ.get("MPIEXEC"))
    add_path(values, os.environ.get("MPIRUN"))
    if qe.get("mpirun"):
        add_path(values, str(qe["mpirun"]))
    for name in ("mpirun", "mpiexec", "srun"):
        add_path(values, shutil.which(name))
    return unique_strings(str(resolve_executable(value, preserve_symlink=True)) for value in values)


def discover_pseudo_dirs(cwd: Path, cfg: Dict[str, Any], explicit_pseudo_dir: Optional[str]) -> List[Dict[str, Any]]:
    qe = cfg.get("qe", {}) if isinstance(cfg.get("qe", {}), dict) else {}
    env_cfg = qe.get("env", {}) if isinstance(qe.get("env", {}), dict) else {}
    raw_values = [
        explicit_pseudo_dir,
        os.environ.get("ESPRESSO_PSEUDO"),
        env_cfg.get("ESPRESSO_PSEUDO"),
        str(cwd / "pseudos"),
        str(cwd.parent / "pseudos"),
        str(Path.home() / "pseudos"),
    ]
    roots = unique_paths([cwd, cwd.parent, Path.home()])
    patterns = ("pseudo", "pseudos", "qe*/pseudo", "q-e*/pseudo", "espresso*/pseudo")
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for pattern in patterns:
            for path in sorted(root.glob(pattern))[:12]:
                raw_values.append(str(path))
    out = []
    for value in unique_strings([str(v) for v in raw_values if v]):
        path = Path(os.path.expandvars(os.path.expanduser(value))).resolve()
        upf_count = len(list(path.glob("*.UPF"))) + len(list(path.glob("*.upf"))) if path.is_dir() else 0
        out.append({"path": str(path), "exists": path.is_dir(), "upf_count": upf_count})
    return out


def check_pw(path: str, env: Dict[str, str], run_checks: bool) -> Dict[str, Any]:
    resolved = resolve_executable(path)
    out: Dict[str, Any] = {"path": str(resolved), "exists": resolved.exists(), "executable": os.access(resolved, os.X_OK)}
    if run_checks and out["exists"] and out["executable"]:
        result = run_command([str(resolved), "-h"], env)
        out.update(result)
        out["run_ok"] = command_looks_like_pw(result)
    else:
        out["run_ok"] = bool(out["exists"] and out["executable"] and not run_checks)
    return out


def check_mpi(path: str, env: Dict[str, str], run_checks: bool) -> Dict[str, Any]:
    resolved = resolve_executable(path, preserve_symlink=True)
    out: Dict[str, Any] = {"path": str(resolved), "exists": resolved.exists(), "executable": os.access(resolved, os.X_OK), "kind": mpi_kind(resolved)}
    if run_checks and out["exists"] and out["executable"]:
        out.update(run_command([str(resolved), "--version"], env))
    return out


def check_pw_with_mpi(pw: str, mpirun: str, env: Dict[str, str], np: int, run_checks: bool) -> Dict[str, Any]:
    if not run_checks:
        return {"run_ok": False, "skipped": True}
    cmd = mpi_prefix(mpirun, np) + [pw, "-h"]
    result = run_command(cmd, env, timeout_s=8)
    result["run_ok"] = command_looks_like_pw(result)
    result["cmd"] = cmd
    return result


def run_command(cmd: List[str], env: Dict[str, str], timeout_s: int = 6) -> Dict[str, Any]:
    proc: Optional[sp.Popen[str]] = None
    try:
        proc = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.STDOUT, text=True, env=env, start_new_session=(os.name != "nt"))
        output, _ = proc.communicate(timeout=timeout_s)
        return {"returncode": proc.returncode, "output_head": (output or "")[:1200]}
    except sp.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        if proc is not None:
            terminate_process_group(proc)
            try:
                more_output, _ = proc.communicate(timeout=2)
                output += more_output or ""
            except Exception:
                pass
        return {"returncode": None, "timeout": True, "output_head": output[:1200]}
    except Exception as exc:
        if proc is not None:
            terminate_process_group(proc)
        return {"returncode": None, "error": str(exc), "output_head": ""}


def terminate_process_group(proc: sp.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=1)
    except Exception:
        try:
            if proc.poll() is None:
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
        except Exception:
            pass


def command_looks_like_pw(result: Dict[str, Any]) -> bool:
    text = str(result.get("output_head") or "").lower()
    if result.get("timeout") or result.get("error"):
        return False
    return "pwscf" in text or "quantum espresso" in text or "usage" in text or result.get("returncode") == 0


def build_recommendation(
    selected_pw: Optional[Dict[str, Any]],
    selected_mpi: Optional[Dict[str, Any]],
    selected_pseudo: Optional[Dict[str, Any]],
    np: int,
    direct_ok: bool,
    mpi_pw_check: Optional[Dict[str, Any]],
    env_cfg: Dict[str, Any],
    prefer_mpi: bool,
) -> Dict[str, Any]:
    env = {"OMP_NUM_THREADS": str(env_cfg.get("OMP_NUM_THREADS", os.environ.get("OMP_NUM_THREADS", "1")))}
    if selected_pseudo and selected_pseudo.get("exists"):
        env["ESPRESSO_PSEUDO"] = selected_pseudo["path"]
    mpirun = None
    if (
        selected_pw
        and selected_pw.get("exists")
        and selected_mpi
        and selected_mpi.get("exists")
        and (prefer_mpi or (not direct_ok and mpi_pw_check and mpi_pw_check.get("run_ok")) or (not direct_ok and selected_mpi.get("executable")))
    ):
        mpirun = selected_mpi["path"]
    return {
        "qe": {
            "mpirun": mpirun,
            "pw": selected_pw["path"] if selected_pw and selected_pw.get("exists") else "pw.x",
            "np": int(np),
            "extra_args": [],
            "env": env,
        }
    }


def classify_status(
    selected_pw: Optional[Dict[str, Any]],
    selected_mpi: Optional[Dict[str, Any]],
    selected_pseudo: Optional[Dict[str, Any]],
    direct_ok: bool,
    mpi_pw_check: Optional[Dict[str, Any]],
) -> str:
    if not selected_pw or not selected_pw.get("exists"):
        return "error_no_pw_x"
    if not selected_pseudo or not selected_pseudo.get("exists") or int(selected_pseudo.get("upf_count", 0)) == 0:
        return "warning_no_pseudo_dir"
    if not selected_pw.get("run_ok") and not (mpi_pw_check and mpi_pw_check.get("run_ok")):
        if selected_mpi and selected_mpi.get("exists") and selected_mpi.get("executable"):
            return "warning_pw_x_run_check_failed"
        return "error_pw_x_not_runnable"
    return "ok"


def build_notes(
    status: str,
    selected_pw: Optional[Dict[str, Any]],
    selected_pseudo: Optional[Dict[str, Any]],
    direct_ok: bool,
    mpi_pw_check: Optional[Dict[str, Any]],
    mpi_checks: List[Dict[str, Any]],
) -> List[str]:
    notes: List[str] = []
    if status == "error_no_pw_x":
        notes.append("pw.x was not found. Set PW_X, QE_BIN, or qe.pw in the config.")
    if status == "error_pw_x_not_runnable":
        notes.append("pw.x was found but did not pass a lightweight run check; inspect dynamic libraries and MPI runtime.")
    if status == "warning_no_pseudo_dir":
        notes.append("No pseudo directory with UPF files was found. Set ESPRESSO_PSEUDO or qe.env.ESPRESSO_PSEUDO.")
    if status == "warning_pw_x_run_check_failed":
        notes.append("pw.x exists and MPI was found, but the lightweight help check did not complete; try the recommended MPI config with a small SCF input.")
    if selected_pw and selected_pw.get("run_ok") and direct_ok:
        notes.append("pw.x passed a direct lightweight check; MPI is optional for np=1.")
    if mpi_pw_check and mpi_pw_check.get("run_ok"):
        notes.append("pw.x passed a lightweight MPI launch check.")
    if any(item.get("kind") == "srun" for item in mpi_checks):
        notes.append("srun was found; on managed clusters prefer scheduler launch rules over hard-coded mpirun.")
    if selected_pseudo and selected_pseudo.get("upf_count"):
        notes.append(f"Pseudo directory contains {selected_pseudo['upf_count']} UPF files.")
    return notes


def select_first_ok(items: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for item in items:
        if item.get("run_ok"):
            return item
    return None


def select_pseudo_dir(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    good = [item for item in items if item.get("exists") and int(item.get("upf_count", 0)) > 0]
    if good:
        return good[0]
    return items[0] if items else None


def resolve_executable(value: str, *, preserve_symlink: bool = False) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    found = shutil.which(expanded)
    path = Path(found or expanded)
    if preserve_symlink:
        if not path.is_absolute():
            path = Path.cwd() / path
        return Path(os.path.abspath(path))
    return path.resolve()


def mpi_kind(path: Path) -> str:
    name = path.name.lower()
    if "srun" in name:
        return "srun"
    if "mpiexec" in name:
        return "mpiexec"
    return "mpirun"


def mpi_prefix(mpirun: str, np: int) -> List[str]:
    kind = mpi_kind(Path(mpirun))
    if kind == "srun":
        return [mpirun, "-n", str(np)]
    return [mpirun, "-np", str(np)]


def add_path(values: List[str], value: Optional[str]) -> None:
    if value:
        values.append(str(value))


def unique_strings(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        key = str(value)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def unique_paths(values: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    seen = set()
    for value in values:
        path = value.expanduser().resolve()
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def print_report(report: Dict[str, Any], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(report, indent=2))
        return
    print(f"status: {report['status']}")
    print("\nrecommended config:")
    print(yaml.safe_dump(report["recommendation"], sort_keys=False).rstrip())
    print("\npw.x candidates:")
    for item in report["pw_candidates"]:
        marker = "ok" if item.get("run_ok") else ("found" if item.get("exists") else "missing")
        print(f"  - [{marker}] {item['path']}")
    print("\nMPI candidates:")
    for item in report["mpi_candidates"]:
        marker = "found" if item.get("exists") else "missing"
        print(f"  - [{marker}] {item['path']} ({item.get('kind')})")
    print("\npseudo candidates:")
    for item in report["pseudo_candidates"]:
        marker = "ok" if item.get("exists") and item.get("upf_count") else ("found" if item.get("exists") else "missing")
        print(f"  - [{marker}] {item['path']} UPF={item.get('upf_count', 0)}")
    if report.get("notes"):
        print("\nnotes:")
        for note in report["notes"]:
            print(f"  - {note}")
