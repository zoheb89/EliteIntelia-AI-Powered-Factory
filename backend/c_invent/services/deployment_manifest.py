import json

def build_customer_manifest(project, blueprint=None, metadata=None, application=None, bi=None):
    return {
        "product": "C INVENT",
        "project_id": project["id"],
        "customer": project["name"],
        "domain": project.get("domain"),
        "target": {
            "platform": "Databricks Lakehouse",
            "layers": ["Bronze", "Silver", "Gold"],
            "orchestration": ["Lakeflow", "Lakeflow Jobs"],
            "operational": "Lakebase if required and supported",
            "application": "Databricks Apps if required and supported",
            "analytics": ["AI/BI", "Genie"]
        },
        "blueprint": blueprint or {},
        "metadata": metadata or {},
        "application": application or {},
        "bi": bi or {},
        "approval_required": True
    }

def to_json(manifest):
    return json.dumps(manifest, indent=2, ensure_ascii=False)
