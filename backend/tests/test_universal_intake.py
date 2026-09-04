from c_invent.services.universal_intake import analyze_intake, classify_documents

def test_one_line_intake_is_domain_agnostic():
    r=analyze_intake("Customer wants to automate manual RFP compliance responses.")
    assert r["mode"] == "universal_intake"
    assert any(x["use_case"] == "document_intelligence" for x in r["candidate_use_cases"])
    assert "security" in r["missing_information"]
    assert r["target_platform_status"] == "unknown"

def test_mixed_enterprise_sources_detected():
    docs=[
        {"name":"RFP.pdf","text":"The solution shall integrate Salesforce CRM and SAP ERP, SharePoint documents and Kafka streaming. Databricks is preferred."},
        {"name":"meeting_notes.txt","text":"Need dashboard KPIs, API integration and customer 360. Security and SLA must be agreed."},
    ]
    r=analyze_intake("Automate the process and reduce manual effort.",docs)
    assert "crm" in r["source_families_detected"]
    assert "erp" in r["source_families_detected"]
    assert "documents" in r["source_families_detected"]
    assert "streaming_iot" in r["source_families_detected"]
    assert r["target_platform_direction"] == "Databricks"
    assert len(r["requirements_signals"]) >= 1

def test_document_classification():
    x=classify_documents([{"name":"Customer_RFP.docx","text":"Request for Proposal: supplier shall provide..."}])
    assert x[0]["type"] == "rfp"
