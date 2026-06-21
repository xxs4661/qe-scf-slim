from __future__ import annotations

import re
from typing import Any, Dict


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _fmt_val(value: Any) -> str:
    if isinstance(value, bool):
        return ".true." if value else ".false."
    if isinstance(value, (int, float)):
        return f"{value}"
    return f"'{value}'"


def _strip_yaml_front_if_any(text: str) -> str:
    text = _normalize_newlines(text)
    yaml_pos = re.search(r"(?mi)^\s*systems\s*:", text)
    amp_pos = re.search(r"(?m)^\s*&", text)
    if yaml_pos and amp_pos and yaml_pos.start() < amp_pos.start():
        return text[amp_pos.start():]
    return text


def _inject_into_section(text: str, section: str, values: Dict[str, Any]) -> str:
    text = _normalize_newlines(text)
    sec = section.upper()
    pat = re.compile(rf"(?mis)^\s*&\s*{sec}\b(.*?)^\s*/\s*$", re.M)
    match = pat.search(text)
    add_block = "\n".join(f"  {key} = {_fmt_val(value)}" for key, value in values.items() if value is not None)
    if match:
        body = match.group(1)
        for key in values:
            body = re.sub(rf"(?mi)^\s*{re.escape(key)}\s*=.*$", "", body)
        lines = [line.rstrip() for line in body.splitlines() if line.strip()]
        new_body = ("\n".join(lines) + ("\n" if lines else "")) + add_block + "\n"
        return text[: match.start()] + f"&{sec}\n{new_body}/\n" + text[match.end():]
    return f"&{sec}\n{add_block}\n/\n" + (text if text.startswith("&") else "\n" + text)


def render_qe_input(
    template_text: str,
    control: Dict[str, Any],
    system: Dict[str, Any],
    electrons: Dict[str, Any],
) -> str:
    text = _strip_yaml_front_if_any(template_text)
    text = _inject_into_section(text, "CONTROL", control)
    text = _inject_into_section(text, "SYSTEM", system)
    return _inject_into_section(text, "ELECTRONS", electrons)

