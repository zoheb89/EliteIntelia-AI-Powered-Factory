"""Regression tests for engagement-name normalization and stage completion.

Uploading a document without typing a name previously produced titles like
"RFP_-_Databricks_Platform_-_11-06-2026.pdf_report (1).pdf".
"""
from api_server import _readable_engagement_name


def test_strips_repeated_extensions_and_download_markers():
    raw = "RFP_-_Databricks_Lakehouse_Platform_Implementation_-_11-06-2026.pdf_report (1).pdf"
    assert _readable_engagement_name(raw) == "RFP - Databricks Lakehouse Platform Implementation - 11-06-2026"


def test_keeps_dates_intact():
    assert _readable_engagement_name("Plan_11-06-2026.pdf") == "Plan 11-06-2026"


def test_leaves_human_typed_names_untouched():
    assert _readable_engagement_name("ITFC Data Platform RFP") == "ITFC Data Platform RFP"


def test_underscores_become_spaces():
    assert _readable_engagement_name("Weqayah_RFI.txt") == "Weqayah RFI"


def test_blank_falls_back_to_default():
    assert _readable_engagement_name("") == "New Engagement"
    assert _readable_engagement_name(None) == "New Engagement"
