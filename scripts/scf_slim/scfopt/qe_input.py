from __future__ import annotations

import re
from typing import Any

# Mask quoted Fortran strings and comments before looking for namelist syntax.
# Their character offsets stay valid against the unmodified input.
_LITERAL = r"'(?:''|[^'])*'" + "|" + r'"(?:""|[^"])*"'
_OPAQUE = re.compile(rf"{_LITERAL}|![^\n]*")
_SCALAR = re.compile(rf"{_LITERAL}|[^\s,!/]+")
_HEADER = re.compile(r"^[ \t]*&[ \t]*(\w+)\b", re.M)
_NAMELISTS = ("CONTROL", "SYSTEM", "ELECTRONS")


def _fmt_val(value: Any) -> str:
    if isinstance(value, bool):
        return ".true." if value else ".false."
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _mask(text: str) -> str:
    return _OPAQUE.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), text)


def _section_end(mask: str, header: re.Match) -> int:
    end = mask.find("/", header.end())
    if end < 0 or _HEADER.search(mask, header.end(), end):
        raise ValueError(f"Missing / at the end of &{header[1]}")
    return end


def template_pseudo_dir(text: str) -> str | None:
    """Read the quoted pseudo_dir that would otherwise move with the job cwd."""
    mask = _mask(text)
    header = next((h for h in _HEADER.finditer(mask) if h[1].upper() == "CONTROL"), None)
    if header is None:
        return None
    result = None
    for key in re.finditer(r"(?i)\bpseudo_dir[ \t]*=", mask[header.end():_section_end(mask, header)]):
        source = text[header.end() + key.end():].lstrip()
        token = _SCALAR.match(source)
        if token:
            value = token[0]
            quote = value[0]
            result = value[1:-1].replace(quote * 2, quote) if quote in ("'", '"') else value
    return result


def _inject_into_section(text: str, section: str, values: dict[str, Any]) -> str:
    values = {key.lower(): value for key, value in values.items() if value is not None}
    mask = _mask(text)
    headers = list(_HEADER.finditer(mask))
    header = next((h for h in headers if h[1].upper() == section), None)
    if header is None:
        # QE reads these namelists in order, before cards such as ATOMIC_SPECIES.
        preceding = _NAMELISTS[:_NAMELISTS.index(section)]
        prior = [h for h in headers if h[1].upper() in preceding]
        pos = _section_end(mask, prior[-1]) + 1 if prior else 0
        block = [f"&{section}", *(f"  {key} = {_fmt_val(v)}" for key, v in values.items()), "/"]
        return text[:pos] + ("\n" if pos else "") + "\n".join(block) + "\n" + text[pos:]

    end = _section_end(mask, header)
    body = text[header.end():end]
    body_mask = mask[header.end():end]
    edits = []
    seen = set()
    for assignment in re.finditer(r"(?i)\b([a-z][a-z0-9_]*)[ \t]*=", body_mask):
        key = assignment[1].lower()
        if key not in values:
            continue
        offset = assignment.end()
        while offset < len(body) and body[offset].isspace():
            offset += 1
        token = _SCALAR.match(body, offset)
        if not token:
            raise ValueError(f"Cannot replace the value of {key} in &{section}")
        edits.append((assignment.start(), token.end(), f"{key} = {_fmt_val(values[key])}"))
        seen.add(key)
    for start, stop, replacement in reversed(edits):
        body = body[:start] + replacement + body[stop:]
    missing = [f"  {key} = {_fmt_val(value)}" for key, value in values.items() if key not in seen]
    if missing:
        body = body.rstrip() + "\n" + "\n".join(missing) + "\n"
    return text[:header.start(1)] + section + body + text[end:]


def render_qe_input(
    template_text: str,
    control: dict[str, Any],
    system: dict[str, Any],
    electrons: dict[str, Any],
) -> str:
    text = template_text.replace("\r\n", "\n").replace("\r", "\n")
    yaml_pos = re.search(r"(?mi)^\s*systems\s*:", text)
    amp_pos = re.search(r"(?m)^\s*&", text)
    if yaml_pos and amp_pos and yaml_pos.start() < amp_pos.start():
        text = text[amp_pos.start():]
    for section, values in zip(_NAMELISTS, (control, system, electrons)):
        text = _inject_into_section(text, section, values)
    return text
