from dataclasses import dataclass
import os
import yaml


@dataclass
class Settings:
    llm_base_url: str
    llm_model: str
    llm_provider: str
    llm_api_key: str
    capgemini_workspace_id: str
    include_workspace_id: bool
    llm_interface: str
    llm_mode: str
    llm_auth_header: str
    llm_auth_scheme: str
    temperature: float
    max_tokens: int
    llm_timeout_seconds: int
    db_host: str
    db_token: str
    db_warehouse_id: str
    allow_mutations: bool
    image_base_url: str
    image_model: str
    image_provider: str
    image_api_key: str
    app_name: str
    app_version: str


# The product is LLM-neutral (spec §1), so configuration must not carry a vendor
# name. `ELITEINTELIA_*` is the supported prefix; the legacy `CAPGEMINI_*` names
# are still read so an existing deployment keeps working through the rename.
PRIMARY_PREFIX = "ELITEINTELIA_"
LEGACY_PREFIXES = ("CAPGEMINI_",)

#: Names that had a vendor word inside them rather than only as a prefix.
LEGACY_ALIASES = {
    "ELITEINTELIA_WORKSPACE_ID": "CAPGEMINI_WORKSPACE_ID",
    "ELITEINTELIA_INCLUDE_WORKSPACE_ID": "CAPGEMINI_INCLUDE_WORKSPACE_ID",
}

_deprecation_warned: set[str] = set()


def _raw_lookup(name, default=""):
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return os.getenv(name, default)


def _candidates(name: str):
    """Every environment name that may supply `name`, most preferred first."""
    yield name
    if name in LEGACY_ALIASES:
        yield LEGACY_ALIASES[name]
    if name.startswith(PRIMARY_PREFIX):
        suffix = name[len(PRIMARY_PREFIX):]
        for legacy in LEGACY_PREFIXES:
            yield legacy + suffix


def _secret(name, default=""):
    """Resolve configuration, preferring the neutral name over the legacy one.

    Reading both means the vendor rename can ship without a coordinated
    environment change; the legacy hit is reported once so operators know what
    to migrate.
    """
    for candidate in _candidates(name):
        value = _raw_lookup(candidate, None)
        if value not in (None, ""):
            if candidate != name and candidate not in _deprecation_warned:
                _deprecation_warned.add(candidate)
                print(f"[config] '{candidate}' is deprecated; rename it to '{name}'.")
            return value
    return default


def legacy_variables_in_use() -> list[dict]:
    """Legacy names currently supplying configuration, for the Settings screen."""
    out = []
    for name in _deprecation_warned:
        neutral = name
        for legacy in LEGACY_PREFIXES:
            if name.startswith(legacy):
                neutral = PRIMARY_PREFIX + name[len(legacy):]
        for new, old in LEGACY_ALIASES.items():
            if old == name:
                neutral = new
        out.append({"legacy": name, "rename_to": neutral})
    return sorted(out, key=lambda d: d["legacy"])


def _bool(v):
    return str(v).lower() in {"1", "true", "yes", "on"}


def load_settings():
    cfg = {}
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        pass

    llm = cfg.get("llm", {})
    db = cfg.get("databricks", {})
    app = cfg.get("app", {})
    image = cfg.get("image", {})

    return Settings(
        llm_base_url=_secret("ELITEINTELIA_LLM_BASE_URL", llm.get("base_url", "")),
        llm_model=_secret("ELITEINTELIA_LLM_MODEL", llm.get("model_name", "openai.gpt-5.1")),
        llm_provider=_secret("ELITEINTELIA_LLM_PROVIDER", llm.get("provider", "azure")),
        llm_api_key=_secret("ELITEINTELIA_LLM_API_KEY", ""),
        capgemini_workspace_id=_secret("ELITEINTELIA_WORKSPACE_ID", ""),
        include_workspace_id=_bool(_secret("ELITEINTELIA_INCLUDE_WORKSPACE_ID", "false")),
        llm_interface=llm.get("model_interface", "langchain"),
        llm_mode=llm.get("mode", "chain"),
        llm_auth_header=_secret(
            "ELITEINTELIA_LLM_AUTH_HEADER", llm.get("auth_header", "x-api-key")
        ),
        llm_auth_scheme=_secret(
            "ELITEINTELIA_LLM_AUTH_SCHEME", llm.get("auth_scheme", "none")
        ),
        temperature=float(_secret("LLM_TEMPERATURE", llm.get("temperature", 0.1))),
        max_tokens=int(_secret("LLM_MAX_TOKENS", llm.get("max_tokens", 4000))),
        llm_timeout_seconds=int(_secret("LLM_TIMEOUT_SECONDS", "90")),
        db_host=_secret("DATABRICKS_HOST", ""),
        db_token=_secret("DATABRICKS_TOKEN", ""),
        db_warehouse_id=_secret("DATABRICKS_WAREHOUSE_ID", ""),
        allow_mutations=_bool(
            _secret("CINVENT_ALLOW_MUTATIONS", db.get("allow_mutations", False))
        ),
        image_base_url=_secret("ELITEINTELIA_IMAGE_BASE_URL", image.get("base_url", "")),
        image_model=_secret("ELITEINTELIA_IMAGE_MODEL", image.get("model_name", "")),
        image_provider=_secret("ELITEINTELIA_IMAGE_PROVIDER", image.get("provider", "")),
        image_api_key=_secret("ELITEINTELIA_IMAGE_API_KEY", ""),
        app_name=app.get("name", "C INVENT"),
        app_version=app.get("version", "0.1.0-poc"),
    )
