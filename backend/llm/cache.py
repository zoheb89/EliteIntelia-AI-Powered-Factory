"""Durable cache for completed model calls.

On a metered plan — 100 calls a week, say — a repeated identical call is spent
budget, not merely latency. Re-running Discovery over evidence that has not
changed should cost nothing.

The store is deliberately conservative: it only ever serves an answer to a
byte-identical request, and a cache failure is swallowed so it can never break
a call that would otherwise have succeeded.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def enabled() -> bool:
    return os.getenv("LLM_CACHE", "on").strip().lower() not in ("off", "0", "false", "no")


def ttl_hours() -> int:
    try:
        return max(0, int(os.getenv("LLM_CACHE_TTL_HOURS", "168")))   # one week
    except ValueError:
        return 168


class DatabaseCache:
    """Cache backed by the application database, so it survives a restart."""

    def __init__(self, session_factory, tenant_id: str = ""):
        self._session_factory = session_factory
        self.tenant_id = tenant_id

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not enabled():
            return None
        from persistence.models import LLMCacheEntry

        with self._session_factory() as s:
            row = s.get(LLMCacheEntry, key)
            if not row:
                return None
            hours = ttl_hours()
            if hours and row.created_at:
                age = datetime.now(timezone.utc) - _aware(row.created_at)
                if age > timedelta(hours=hours):
                    return None
            row.hits = (row.hits or 0) + 1
            row.last_used_at = datetime.now(timezone.utc)
            s.commit()
            return {"text": row.text, "model": row.model, "provider": row.provider}

    def put(self, key: str, payload: Dict[str, Any]) -> None:
        if not enabled():
            return
        from persistence.models import LLMCacheEntry

        with self._session_factory() as s:
            if s.get(LLMCacheEntry, key):
                return
            s.add(LLMCacheEntry(
                key=key, tenant_id=self.tenant_id,
                provider=payload.get("provider", ""), model=payload.get("model", ""),
                text=payload.get("text", "")))
            s.commit()

    def stats(self) -> Dict[str, Any]:
        """What the cache has actually saved — calls not spent."""
        from sqlalchemy import func, select

        from persistence.models import LLMCacheEntry

        with self._session_factory() as s:
            entries = s.scalar(select(func.count()).select_from(LLMCacheEntry)) or 0
            saved = s.scalar(select(func.coalesce(func.sum(LLMCacheEntry.hits), 0))) or 0
        return {"enabled": enabled(), "entries": int(entries),
                "calls_saved": int(saved), "ttl_hours": ttl_hours()}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
