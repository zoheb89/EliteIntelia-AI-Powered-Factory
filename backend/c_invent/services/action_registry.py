"""Metadata-driven delivery action registry.

Actions live in config.yaml rather than in Streamlit page logic. The engine only
interprets generic boolean conditions against persisted lifecycle state. This
keeps the delivery factory platform/domain neutral and makes the next action
reproducible from metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass(frozen=True)
class ActionSpec:
    id: str
    title: str
    description: str
    workspace: str
    output: str
    approval: str
    when: tuple[str, ...]


def _load_metadata() -> List[ActionSpec]:
    root = Path(__file__).resolve().parents[2]
    cfg_path = root / "config.yaml"
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        raw = ((data.get("lifecycle") or {}).get("actions") or [])
    except Exception:
        raw = []
    specs = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        specs.append(ActionSpec(
            id=str(item["id"]),
            title=str(item.get("title") or item["id"]),
            description=str(item.get("description") or ""),
            workspace=str(item.get("workspace") or ""),
            output=str(item.get("output") or ""),
            approval=str(item.get("approval") or "none"),
            when=tuple(str(x) for x in (item.get("when") or [])),
        ))
    return specs


ACTIONS: List[ActionSpec] = _load_metadata()


def _condition(value: str, state: Dict[str, Any]) -> bool:
    value = value.strip()
    if value.startswith("not:"):
        return not bool(state.get(value[4:]))
    return bool(state.get(value))


def applicable_actions(state: Dict[str, Any]) -> List[ActionSpec]:
    return [a for a in ACTIONS if all(_condition(c, state) for c in a.when)]


def next_action_spec(state: Dict[str, Any]) -> Optional[ActionSpec]:
    items = applicable_actions(state)
    return items[0] if items else None


def action_context(spec: Optional[ActionSpec], state: Dict[str, Any]) -> Dict[str, Any]:
    if not spec:
        return {"state": "COMPLETE", "message": "Delivery lifecycle complete."}
    return {
        "action_id": spec.id,
        "title": spec.title,
        "description": spec.description,
        "workspace": spec.workspace,
        "expected_output": spec.output,
        "approval": spec.approval,
        "conditions": list(spec.when),
        "source_state": {k: v for k, v in state.items() if isinstance(v, (bool, str))},
    }
