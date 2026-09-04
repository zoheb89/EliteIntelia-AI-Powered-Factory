"""Configuration must be vendor-neutral (spec §1) without breaking deployments.

`ELITEINTELIA_*` is the supported prefix. The legacy `CAPGEMINI_*` names are
still read so an existing Render deployment keeps working through the rename.
"""
import importlib

import pytest

import c_invent.services.config as config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in list(config.os.environ):
        if name.startswith(("ELITEINTELIA_", "CAPGEMINI_")):
            monkeypatch.delenv(name, raising=False)
    importlib.reload(config)
    yield
    importlib.reload(config)


def test_neutral_name_is_read(monkeypatch):
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "neutral")
    assert config.load_settings().llm_api_key == "neutral"


def test_legacy_name_still_works(monkeypatch):
    """An existing deployment must not break on the rename."""
    monkeypatch.setenv("CAPGEMINI_LLM_API_KEY", "legacy")
    assert config.load_settings().llm_api_key == "legacy"


def test_neutral_name_wins_over_legacy(monkeypatch):
    monkeypatch.setenv("CAPGEMINI_LLM_API_KEY", "legacy")
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "neutral")
    assert config.load_settings().llm_api_key == "neutral"


def test_legacy_alias_without_a_matching_prefix(monkeypatch):
    """WORKSPACE_ID carried the vendor word inside the name, not as a prefix."""
    monkeypatch.setenv("CAPGEMINI_WORKSPACE_ID", "ws-1")
    assert config.load_settings().capgemini_workspace_id == "ws-1"


def test_empty_legacy_value_falls_through_to_default(monkeypatch):
    monkeypatch.setenv("CAPGEMINI_LLM_API_KEY", "")
    assert config.load_settings().llm_api_key == ""


def test_legacy_use_is_reported_for_migration(monkeypatch):
    monkeypatch.setenv("CAPGEMINI_LLM_API_KEY", "legacy")
    config.load_settings()
    hints = {h["legacy"]: h["rename_to"] for h in config.legacy_variables_in_use()}
    assert hints["CAPGEMINI_LLM_API_KEY"] == "ELITEINTELIA_LLM_API_KEY"


def test_neutral_only_deployment_reports_nothing_to_migrate(monkeypatch):
    monkeypatch.setenv("ELITEINTELIA_LLM_API_KEY", "neutral")
    config.load_settings()
    assert config.legacy_variables_in_use() == []


@pytest.mark.parametrize("suffix", [
    "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER", "LLM_API_KEY",
    "LLM_AUTH_HEADER", "LLM_AUTH_SCHEME",
    "IMAGE_BASE_URL", "IMAGE_MODEL", "IMAGE_PROVIDER", "IMAGE_API_KEY",
])
def test_every_renamed_variable_still_accepts_the_legacy_name(monkeypatch, suffix):
    monkeypatch.setenv(f"CAPGEMINI_{suffix}", "from-legacy")
    assert config._secret(f"ELITEINTELIA_{suffix}", "") == "from-legacy"


def test_no_vendor_name_is_required_to_configure_the_product():
    """The product must be configurable without any vendor-specific variable."""
    import inspect
    source = inspect.getsource(config.load_settings)
    assert "CAPGEMINI_" not in source, "load_settings still requests a vendor-named variable"
