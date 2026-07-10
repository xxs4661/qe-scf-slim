from __future__ import annotations

from typing import Any, Dict, Optional


class ScfSlimError(RuntimeError):
    code = "scf_slim_error"

    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class ConfigError(ScfSlimError):
    code = "config_error"


class PreflightError(ScfSlimError):
    code = "preflight_error"

    def __init__(self, report: Dict[str, Any]) -> None:
        self.report = dict(report)
        errors = report.get("errors") or ["unknown preflight error"]
        super().__init__("Preflight failed: " + "; ".join(str(item) for item in errors), details=report)


class ResumeError(ScfSlimError):
    code = "resume_error"


class FatalRunError(ScfSlimError):
    code = "fatal_run_error"
