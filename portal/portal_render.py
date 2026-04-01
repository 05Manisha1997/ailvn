"""
portal/portal_render.py

Single implementation for:
- Loading intent templates from Cosmos (via InsurancePortal)
- Replacing {rag.slot_name} placeholders with values from RAG / extractors
- Used by the REST Portal API and by agents.tasks after intent + RAG.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from portal.insurance_portal import get_insurance_portal

_RAG_SLOT = re.compile(r"\{rag\.(\w+)\}")


@dataclass
class PortalRenderResult:
    intent: str
    rendered_text: str
    template_raw: str
    slots_requested: list[str] = field(default_factory=list)
    slots_filled: dict[str, Any] = field(default_factory=dict)
    voice_id: str | None = None


def extract_rag_slots(template: str) -> list[str]:
    """Unique slot names in template order of first appearance."""
    seen: dict[str, None] = {}
    for m in _RAG_SLOT.finditer(template or ""):
        name = m.group(1)
        if name not in seen:
            seen[name] = None
    return list(seen.keys())


def render_portal_response(
    intent: str,
    rag_values: dict[str, Any],
    *,
    fallback: str = "information not available",
) -> PortalRenderResult:
    """
    Fetch template for intent from DB (Cosmos-backed InsurancePortal), fill {rag.*} slots.
    """
    portal = get_insurance_portal()
    tmpl = portal.get_template(intent)
    raw = tmpl.template
    slots = extract_rag_slots(raw)
    filled = {k: rag_values.get(k) for k in slots if rag_values.get(k) not in (None, "")}
    text = portal.fill_template(intent, rag_values, fallback=fallback)
    return PortalRenderResult(
        intent=intent,
        rendered_text=text,
        template_raw=raw,
        slots_requested=slots,
        slots_filled=filled,
        voice_id=tmpl.voice_id,
    )
