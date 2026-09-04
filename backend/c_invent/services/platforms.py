"""Generic target-platform selection, detection and provisioning-state logic.

C INVENT is platform-neutral. This module contains metadata about supported target
platforms and the state machine for onboarding them. It deliberately stores no
customer secrets in the project database.
"""
import os
import re
from datetime import datetime, timezone

PLATFORM_CATALOG = {
    "Databricks": {"type": "SaaS", "clouds": ["Azure", "AWS", "GCP"], "endpoint_hint": "*.cloud.databricks.com", "fit_profile": {"data_engineering": 0.96, "application": 0.72, "lakehouse": 0.97, "warehouse": 0.82, "governance": 0.92, "integration": 0.88, "analytics_ai": 0.95}},
    "Microsoft Fabric": {"type": "SaaS", "clouds": ["Azure"], "endpoint_hint": "app.fabric.microsoft.com", "fit_profile": {"data_engineering": 0.88, "application": 0.62, "lakehouse": 0.86, "warehouse": 0.92, "governance": 0.90, "integration": 0.84, "analytics_ai": 0.90}},
    "Snowflake": {"type": "SaaS", "clouds": ["Azure", "AWS", "GCP"], "endpoint_hint": "<account>.<region>.snowflakecomputing.com", "fit_profile": {"data_engineering": 0.88, "application": 0.68, "lakehouse": 0.84, "warehouse": 0.97, "governance": 0.95, "integration": 0.90, "analytics_ai": 0.88}},
    "BigQuery": {"type": "SaaS", "clouds": ["GCP"], "endpoint_hint": "bigquery.googleapis.com", "fit_profile": {"data_engineering": 0.88, "application": 0.62, "lakehouse": 0.80, "warehouse": 0.96, "governance": 0.88, "integration": 0.82, "analytics_ai": 0.96}},
    "Amazon Redshift": {"type": "PaaS", "clouds": ["AWS"], "endpoint_hint": "<cluster>.<region>.redshift.amazonaws.com", "fit_profile": {"data_engineering": 0.78, "application": 0.62, "lakehouse": 0.68, "warehouse": 0.92, "governance": 0.82, "integration": 0.84, "analytics_ai": 0.78}},
    "Azure Synapse": {"type": "PaaS", "clouds": ["Azure"], "endpoint_hint": "<workspace>.sql.azuresynapse.net", "fit_profile": {"data_engineering": 0.82, "application": 0.60, "lakehouse": 0.74, "warehouse": 0.90, "governance": 0.88, "integration": 0.90, "analytics_ai": 0.82}},
    "Azure SQL": {"type": "PaaS", "clouds": ["Azure"], "endpoint_hint": "<server>.database.windows.net", "fit_profile": {"data_engineering": 0.62, "application": 0.94, "lakehouse": 0.42, "warehouse": 0.76, "governance": 0.90, "integration": 0.96, "analytics_ai": 0.68}},
    "Other": {"type": "Custom", "clouds": ["Azure", "AWS", "GCP", "On-premises", "Other"], "endpoint_hint": "Customer supplied", "fit_profile": {"data_engineering": 0.55, "application": 0.55, "lakehouse": 0.55, "warehouse": 0.55, "governance": 0.55, "integration": 0.55, "analytics_ai": 0.55}},
}

SUPPORTED_PLATFORMS = list(PLATFORM_CATALOG)

# Metadata-driven environment input model. These are labels/help only; secret values are
# never persisted. Existing-environment verification needs an endpoint and secret reference.
# Provisioning needs the customer cloud/resource context instead of an endpoint.
ENVIRONMENT_FIELDS = {
    "existing": {
        "endpoint": {"label": "Customer platform endpoint / account URL", "required": True, "placeholder": "https://<customer-endpoint>", "help": "Workspace, account, tenant, or service endpoint used to reach the customer platform."},
        "credential_ref": {"label": "Credential reference (secret NAME only)", "required": True, "placeholder": "CINVENT_CUSTOMER_<PLATFORM>_CREDENTIAL", "help": "Reference secret name(s) configured in the deployment environment. Never paste a token, password, private key, or client secret here."},
        "auth_method": {"label": "Authentication method", "required": False, "options": ["OAuth / Service Principal", "OAuth / User", "API Token / PAT (legacy where applicable)", "Customer-managed connection", "Other"]},
        "environment_name": {"label": "Customer environment name", "required": False, "placeholder": "Production / Development / UAT"},
        "region": {"label": "Cloud region", "required": False, "placeholder": "e.g. Azure East US 2"},
    },
    "provision": {
        "account_scope": {"label": "Customer cloud account / subscription / project", "required": True, "placeholder": "Customer subscription, AWS account, or GCP project ID", "help": "The customer-owned cloud scope where C INVENT is authorized to provision resources."},
        "region": {"label": "Target cloud region", "required": True, "placeholder": "e.g. East US 2"},
        "environment_name": {"label": "Environment name", "required": True, "placeholder": "Development / Test / Production"},
        "credential_ref": {"label": "Provisioning credential reference (secret NAME only)", "required": True, "placeholder": "CINVENT_CUSTOMER_<CLOUD>_PROVISIONER", "help": "Reference the customer-managed deployment identity/secret. Never paste credentials."},
        "iac_repository": {"label": "IaC / deployment repository", "required": False, "placeholder": "https://git.example.com/customer/platform-iac"},
        "network_context": {"label": "Network / connectivity context", "required": False, "placeholder": "VNet/VPC, private endpoints, VPN/ExpressRoute details"},
    },
}

def environment_fields(mode):
    return ENVIRONMENT_FIELDS.get(mode or "existing", {})



def now():
    return datetime.now(timezone.utc).isoformat()


def normalize_platform(value):
    if not value:
        return ""
    v = str(value).strip().lower()
    aliases = {
        "fabric": "Microsoft Fabric", "microsoft fabric": "Microsoft Fabric",
        "databricks": "Databricks", "snowflake": "Snowflake",
        "bigquery": "BigQuery", "google bigquery": "BigQuery",
        "redshift": "Amazon Redshift", "amazon redshift": "Amazon Redshift",
        "synapse": "Azure Synapse", "azure synapse": "Azure Synapse",
        "azure sql": "Azure SQL", "sql server": "Azure SQL",
    }
    return aliases.get(v, value if value in PLATFORM_CATALOG else "Other")


def detect_platform(endpoint, hint=""):
    """Best-effort endpoint detection; never claims a connection was verified."""
    text = (endpoint or "").strip().lower()
    if not text:
        return normalize_platform(hint) if hint else ""
    rules = [
        (r"databricks\.com$|\.cloud\.databricks\.com$", "Databricks"),
        (r"fabric\.microsoft\.com$|api\.fabric\.microsoft\.com$", "Microsoft Fabric"),
        (r"snowflakecomputing\.com$", "Snowflake"),
        (r"bigquery\.googleapis\.com$|bigquery\.cloud\.google\.com$", "BigQuery"),
        (r"redshift\.amazonaws\.com$", "Amazon Redshift"),
        (r"sql\.azuresynapse\.net$", "Azure Synapse"),
        (r"database\.windows\.net$", "Azure SQL"),
    ]
    host = re.sub(r"^https?://", "", text).split("/", 1)[0]
    for pattern, platform in rules:
        if re.search(pattern, host):
            return platform
    return normalize_platform(hint) if hint else "Other"



def secret_value(name):
    """Resolve a referenced deployment secret without exposing or persisting its value.

    Supports Streamlit Cloud flat secrets (the normal POC setup) and environment
    variables. A credential reference is always treated as a *secret name*, never
    as a token value.
    """
    if not name:
        return ""
    key = str(name).strip()
    if not key:
        return ""

    # Environment variables are useful for CI/CD and local deployments.
    value = os.getenv(key, "")
    if value:
        return str(value)

    try:
        import streamlit as st
        secrets = st.secrets
        # Standard Streamlit Cloud usage: DATABRICKS_PAT = "..."
        value = secrets.get(key, "")
        if value:
            return str(value)
        # Also tolerate a nested [credentials] section without changing the
        # persisted project contract.
        for section in ("credentials", "secrets", "databricks"):
            try:
                block = secrets.get(section)
                if hasattr(block, "get"):
                    value = block.get(key, "")
                    if value:
                        return str(value)
            except Exception:
                continue
    except Exception:
        pass
    return ""

def secret_status(config):
    """Resolve only presence of configured secrets, never return secret values."""
    p = normalize_platform(config.get("platform"))
    ref = str(config.get("credential_ref") or "").strip()
    if not ref:
        return {"configured": False, "source": "none"}
    # The ref is an environment/secret name, not a secret value.
    names = [x.strip() for x in ref.split(",") if x.strip()]
    present = all(bool(secret_value(n)) for n in names)
    return {"configured": present, "source": "environment_secret", "reference": ref, "platform": p}


def derive_state(config):
    """Return a deterministic, explainable onboarding state for the UI and gates."""
    c = config or {}
    platform = normalize_platform(c.get("platform"))
    mode = c.get("environment_mode") or ""
    endpoint = (c.get("endpoint") or "").strip()
    decision_status = c.get("decision_status") or "not_selected"
    detected = detect_platform(endpoint, platform) if endpoint else ""
    secret = secret_status(c)
    credential_ref = str(c.get("credential_ref") or "").strip()
    verified = bool(c.get("verified_at"))
    plan_ready = bool(c.get("provisioning_plan"))

    if not platform:
        return {"state": "NOT_SELECTED", "label": "Target platform not selected", "next_action": "Select the approved target platform.", "detected_platform": detected}
    if decision_status != "selected":
        return {"state": "DIRECTION_ONLY", "label": "Platform is only a proposed direction", "next_action": "Confirm the final platform decision after architecture approval.", "detected_platform": detected}
    if not mode:
        return {"state": "CONFIGURATION_REQUIRED", "label": "Deployment path not selected", "next_action": "Choose existing customer environment or C INVENT provisioning/IaC.", "detected_platform": detected}
    if mode == "existing" and not endpoint:
        return {"state": "ENDPOINT_REQUIRED", "label": "Customer endpoint required", "next_action": "Enter the customer platform endpoint; C INVENT will auto-detect where possible.", "detected_platform": detected}
    if mode == "existing" and detected and platform != detected and platform != "Other":
        return {"state": "PLATFORM_MISMATCH", "label": "Endpoint does not match selected platform", "next_action": f"Confirm the selected platform ({platform}) or correct the endpoint.", "detected_platform": detected}
    # A previously verified customer environment remains a persisted evidence state
    # even if the deployment secret is temporarily unavailable after a process restart.
    # Mutation/execution controls still require the live secret, so this does not grant
    # access to Databricks; it only preserves the lifecycle evidence gate.
    snapshot = c.get("verification_snapshot") or {}
    if mode == "existing" and verified:
        return {"state": "VERIFIED", "label": "Customer platform verified", "next_action": "Refresh Environment Assessment to persist the verified capability evidence.", "detected_platform": detected}
    if mode == "existing" and not secret["configured"]:
        return {"state": "CREDENTIALS_REQUIRED", "label": "Referenced customer secret is not available", "next_action": f"Add the secret named {credential_ref or '<SECRET_NAME>'} to the deployment environment, then save and verify connectivity.", "detected_platform": detected}
    if mode == "existing":
        return {"state": "READY_TO_VERIFY", "label": "Customer platform is ready to verify", "next_action": "Run platform verification using the customer credential reference.", "detected_platform": detected}
    if mode == "provision":
        if not plan_ready:
            return {"state": "PROVISIONING_PLAN_REQUIRED", "label": "Provisioning plan required", "next_action": "Generate the platform-specific cloud/IaC plan and obtain human approval before execution.", "detected_platform": detected}
        if verified:
            return {"state": "VERIFIED", "label": "Provisioned customer platform verified", "next_action": "Refresh Environment Assessment.", "detected_platform": detected}
        return {"state": "PLAN_READY", "label": "Provisioning plan ready", "next_action": "Review/approve the plan, execute it with authorized credentials, then verify the deployed platform.", "detected_platform": detected}
    return {"state": "CONFIGURATION_REQUIRED", "label": "Platform onboarding needs configuration", "next_action": "Complete the platform onboarding fields.", "detected_platform": detected}
