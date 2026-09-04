"""Auth (hashing, tokens, RBAC) and sandbox pipeline execution."""
import os
import tempfile
from pathlib import Path

import pytest

from c_invent.services import auth as A
from c_invent.services.pipeline_compiler import starter_pipeline
from c_invent.services.pipeline_runner import run_sandbox, _resolve_sql, _rewrite_casts


# ------------------------------------------------------------------ passwords
def test_password_hash_roundtrip():
    h = A.hash_password("CorrectHorse123")
    assert h.startswith("pbkdf2$")
    assert A.verify_password("CorrectHorse123", h)
    assert not A.verify_password("wrong-password", h)


def test_password_hash_is_salted():
    assert A.hash_password("SamePassword1") != A.hash_password("SamePassword1")


def test_short_password_rejected():
    with pytest.raises(A.AuthError):
        A.hash_password("short")


# --------------------------------------------------------------------- tokens
def test_token_roundtrip(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "unit-test-secret")
    tok = A.issue_token("a@b.com", "editor", "Ann")
    payload = A.verify_token(tok)
    assert payload["sub"] == "a@b.com"
    assert payload["role"] == "editor"


def test_tampered_token_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "unit-test-secret")
    body, _sig = A.issue_token("a@b.com", "viewer").split(".")
    forged = A.issue_token("a@b.com", "admin").split(".")[0]
    with pytest.raises(A.AuthError):
        A.verify_token(f"{forged}.{_sig}")
    with pytest.raises(A.AuthError):
        A.verify_token(f"{body}.deadbeef")


def test_expired_token_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "unit-test-secret")
    monkeypatch.setattr(A, "TOKEN_TTL_SECONDS", -10)
    with pytest.raises(A.AuthError):
        A.verify_token(A.issue_token("a@b.com", "viewer"))


# ----------------------------------------------------------------------- RBAC
@pytest.mark.parametrize("role,level,allowed", [
    ("admin", "admin", True), ("admin", "editor", True),
    ("editor", "editor", True), ("editor", "admin", False),
    ("viewer", "viewer", True), ("viewer", "editor", False),
])
def test_require_role(role, level, allowed):
    user = {"role": role}
    if allowed:
        A.require_role(user, level)
    else:
        with pytest.raises(A.AuthError):
            A.require_role(user, level)


# ---------------------------------------------------------------- user store
def _store():
    tmp = Path(tempfile.mkdtemp()) / "users.db"
    return A.UserStore(tmp)


def test_user_create_and_authenticate():
    s = _store()
    s.create("dev@elite.io", "Password123", "Dev", "editor")
    user = s.authenticate("dev@elite.io", "Password123")
    assert user["role"] == "editor"


def test_authenticate_rejects_bad_password():
    s = _store()
    s.create("dev@elite.io", "Password123")
    with pytest.raises(A.AuthError):
        s.authenticate("dev@elite.io", "Password124")


def test_unknown_user_rejected():
    with pytest.raises(A.AuthError):
        _store().authenticate("ghost@elite.io", "whatever123")


def test_duplicate_email_rejected():
    s = _store()
    s.create("dev@elite.io", "Password123")
    with pytest.raises(A.AuthError):
        s.create("dev@elite.io", "Password123")


def test_invalid_role_rejected():
    with pytest.raises(A.AuthError):
        _store().create("x@elite.io", "Password123", role="superuser")


# ------------------------------------------------------------ sandbox runner
def test_cast_rewrite_preserves_text():
    """`cast(x as string)` in SQLite yields 0 and destroys data; must map to TEXT."""
    assert "as TEXT" in _rewrite_casts("select cast(order_status as string) as s from t")
    assert "as INTEGER" in _rewrite_casts("select cast(id as bigint) from t")
    assert "as REAL" in _rewrite_casts("select cast(amt as decimal(18,2)) from t")


def test_resolve_sql_expands_refs():
    sql = _resolve_sql("{{ config(materialized='view') }}\nselect * from {{ ref('stg') }}")
    assert "{{" not in sql and "stg" in sql


def test_resolve_sql_expands_sources():
    assert "raw__orders" in _resolve_sql("select * from {{ source('raw', 'orders') }}")


def test_sandbox_executes_full_pipeline():
    r = run_sandbox(starter_pipeline())
    assert r["ok"] is True
    assert r["engine"] == "sandbox"
    assert [n["status"] for n in r["nodes"]] == ["success"] * 3


def test_sandbox_filter_actually_filters():
    """Regression: a broken CAST silently kept every row."""
    r = run_sandbox(starter_pipeline())
    counts = {n["model"]: n["row_count"] for n in r["nodes"]}
    assert counts["raw_orders"] == 60
    assert counts["stg_orders_valid"] < counts["raw_orders"]


def test_sandbox_returns_sample_rows():
    r = run_sandbox(starter_pipeline())
    gold = next(n for n in r["nodes"] if n["model"] == "fct_customer_revenue")
    assert gold["sample"]["columns"] == ["customer_id", "total_revenue", "order_count"]
    assert len(gold["sample"]["rows"]) > 0


def test_sandbox_runs_data_quality_tests():
    r = run_sandbox(starter_pipeline())
    assert r["tests"], "expected generic tests to run"
    assert all(t["status"] == "pass" for t in r["tests"])


def test_sandbox_refuses_broken_pipeline():
    p = starter_pipeline()
    p["edges"].append({"id": "cyc", "source": "n3", "target": "n1"})
    r = run_sandbox(p)
    assert r["ok"] is False
    assert r["nodes"] == []
