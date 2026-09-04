"""Domain/use-case agnostic intake analysis for C INVENT.

Deterministic first-pass analysis. It never claims inferred items are customer facts;
all extracted signals are tagged as evidence/signals and confidence.
"""
import re, json, zipfile, io
from collections import Counter

DOC_TYPES = {
    "rfi": ["rfi", "request for information"],
    "rfp": ["rfp", "request for proposal", "proposal request"],
    "rfq": ["rfq", "request for quotation", "request for quote"],
    "sow": ["sow", "statement of work"],
    "proposal": ["proposal", "solution proposal"],
    "meeting_notes": ["meeting notes", "minutes of meeting", "mom", "workshop notes", "discovery notes"],
    "email": ["email", "from:", "to:", "subject:"],
    "requirements": ["requirements", "functional requirement", "technical requirement"],
}

DOMAIN_SIGNALS = {
    "financial_services": ["bank", "banking", "loan", "payment", "finance", "aml", "kyc"],
    "government": ["government", "ministry", "public sector", "municipality", "authority"],
    "telecom": ["telecom", "subscriber", "network", "5g", "bss", "oss"],
    "manufacturing": ["manufacturing", "factory", "production", "plant", "machine", "mes"],
    "retail": ["retail", "store", "ecommerce", "customer order", "pos"],
    "healthcare": ["hospital", "patient", "clinical", "healthcare", "medical"],
    "logistics": ["logistics", "shipment", "warehouse", "fleet", "delivery", "transport"],
    "insurance": ["insurance", "policy", "claim", "underwriting"],
    "education": ["university", "school", "student", "education", "campus"],
}

SOURCE_PATTERNS = {
    "crm": r"\b(salesforce|dynamics\s*365|hubspot|crm)\b",
    "erp": r"\b(sap|oracle\s*(erp|fusion)|dynamics\s*(365\s*)?(finance|supply)|erp)\b",
    "sql_database": r"\b(sql server|postgres(?:ql)?|mysql|oracle database|database|db2)\b",
    "documents": r"\b(sharepoint|document management|dms|file share|sftp|pdf|word|excel|documents?)\b",
    "email": r"\b(outlook|exchange|email|mailbox|inbox)\b",
    "api": r"\b(api|rest|soap|web service)\b",
    "streaming_iot": r"\b(kafka|event hub|iot|sensor|telemetry|streaming|real[- ]time events?)\b",
    "cloud_storage": r"\b(s3|adls|azure blob|gcs|object storage|data lake)\b",
}

USE_CASE_PATTERNS = {
    "document_intelligence": ["extract", "document", "ocr", "classif", "rfi", "rfp", "compliance"],
    "analytics_reporting": ["dashboard", "report", "kpi", "analytics", "bi", "insight"],
    "data_modernization": ["migrate", "modernize", "data warehouse", "lakehouse", "etl", "elt", "legacy"],
    "customer_360": ["customer 360", "customer view", "customer profile", "360"],
    "integration": ["integrat", "interface", "api", "sync", "connect"],
    "ai_ml": ["ai", "machine learning", "ml", "genai", "copilot", "prediction", "recommendation"],
    "workflow_automation": ["automate", "workflow", "approval", "manual effort", "process automation"],
    "iot_streaming": ["iot", "sensor", "telemetry", "streaming", "real-time"],
}

MISSING_CHECKS = [
    ("business_owner", ["owner", "sponsor", "stakeholder", "business user"]),
    ("source_inventory", ["source", "system", "database", "sharepoint", "crm", "erp"]),
    ("sample_data", ["sample data", "sample file", "dataset", "extract", "attachment"]),
    ("volume", ["gb", "tb", "million", "records", "volume", "daily volume"]),
    ("sla", ["sla", "latency", "response time", "batch window", "refresh"]),
    ("security", ["security", "privacy", "pii", "personal data", "classification"]),
    ("integration", ["api", "integration", "interface", "connectivity"]),
    ("acceptance", ["acceptance", "success criteria", "kpi", "target", "accuracy"]),
]


def _norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _norm_lines(text):
    """Collapse horizontal whitespace but keep line breaks.

    `_norm` flattens newlines, which makes the `\n+` branch of the sentence
    splitter unreachable: a heading or a table cell with no terminal
    punctuation is then glued onto whatever follows it, producing requirements
    like "Weqayah Discovery Assessment Questionnaire The patient completes
    registration...". Line structure is the only sentence boundary such
    documents have.
    """
    t = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    return re.sub(r"\n{2,}", "\n", t).strip()


def classify_documents(documents):
    out = []
    for d in documents:
        text = _norm(d.get("text", "")).lower()
        name = _norm(d.get("name", "")).lower()
        scores = Counter()
        for typ, terms in DOC_TYPES.items():
            scores[typ] = sum(1 for t in terms if t in name or t in text)
        typ, score = scores.most_common(1)[0] if scores else ("unknown", 0)
        out.append({"name": d.get("name", ""), "type": typ if score else "unknown", "signal_count": score, "characters": len(d.get("text", ""))})
    return out


def analyze_intake(customer_intent, documents=None):
    documents = documents or []
    joined = "\n\n".join([customer_intent or ""] + [d.get("text", "") for d in documents])
    text = _norm(joined)
    low = text.lower()
    doc_types = classify_documents(documents)

    domains = []
    for domain, terms in DOMAIN_SIGNALS.items():
        hits = sum(low.count(t) for t in terms)
        if hits:
            domains.append({"domain": domain, "signal_count": hits})
    domains.sort(key=lambda x: x["signal_count"], reverse=True)

    sources = []
    for source, pattern in SOURCE_PATTERNS.items():
        if re.search(pattern, low):
            sources.append(source)

    use_cases = []
    for uc, terms in USE_CASE_PATTERNS.items():
        hits = sum(low.count(t) for t in terms)
        if hits:
            use_cases.append({"use_case": uc, "signal_count": hits})
    use_cases.sort(key=lambda x: x["signal_count"], reverse=True)

    requirement_lines = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", _norm_lines(joined)):
        s = sentence.strip(" -•\t")
        sl = s.lower()
        if len(s) >= 20 and any(k in sl for k in ["must ", "shall ", "should ", "need to ", "needs to ", "required", "requirement", "objective", "automate", "provide "]):
            requirement_lines.append(s[:500])
    # preserve order and cap to avoid turning intake into an unbounded prompt
    seen = set(); requirements=[]
    for x in requirement_lines:
        key=x.lower()
        if key not in seen:
            seen.add(key); requirements.append(x)
    requirements = requirements[:40]

    missing=[]
    for key, terms in MISSING_CHECKS:
        if not any(t in low for t in terms):
            missing.append(key)

    platform = "unknown"
    for p, terms in {
        "Databricks":["databricks"], "Snowflake":["snowflake"], "Microsoft Fabric":["fabric"],
        "Azure Synapse":["synapse"], "BigQuery":["bigquery"], "Amazon Redshift":["redshift"]}.items():
        if any(t in low for t in terms): platform=p; break

    return {
        "version": "0.1.24",
        "mode": "universal_intake",
        "customer_intent_present": bool(_norm(customer_intent)),
        "evidence_files": doc_types,
        "document_type_summary": dict(Counter(x["type"] for x in doc_types)),
        "domain_signals": domains[:5],
        "domain_status": "signal_only" if domains else "unknown",
        "candidate_use_cases": use_cases[:8],
        "source_families_detected": sources,
        "requirements_signals": requirements,
        "target_platform_direction": platform,
        "target_platform_status": "customer_stated_direction" if platform != "unknown" else "unknown",
        "missing_information": missing,
        "evidence_quality": {
            "intent": "available" if customer_intent else "missing",
            "documents": "available" if documents else "missing",
            "structured_source_inventory": "present" if "source_inventory" not in missing else "missing",
            "sample_data": "present" if "sample_data" not in missing else "missing",
        },
        "guardrails": [
            "Signals are not customer-approved facts.",
            "Domain and use-case labels are hypotheses until Discovery confirms them.",
            "Target platform direction is not selection, provisioning or verification evidence.",
            "Missing information becomes a discovery question rather than an invented assumption.",
        ],
        "recommended_next_step": "Run AI Discovery with the complete intake evidence; do not lock architecture from intake alone.",
    }


def build_intake_bundle(analysis, documents):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("intake_analysis.json", json.dumps(analysis, indent=2, ensure_ascii=False))
        z.writestr("README.txt", "C INVENT Universal Intake Engine 0.1.24\n\nSignals are not customer-approved facts. Use Discovery to validate and enrich them.\n")
        for d in documents:
            z.writestr("evidence/" + d.get("name", "document.txt"), d.get("text", ""))
    return bio.getvalue()
