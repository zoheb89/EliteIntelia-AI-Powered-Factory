"""PDF report generation (spec §29).

Every lifecycle stage can be rendered as a branded PDF built from the *current*
canonical state, so a document can never quietly represent an older version of
the project.

Two rules the renderer enforces:

* **Provenance travels into the document.** A statement printed in a PDF carries
  the same badge it has on screen, so a reader outside the tool cannot mistake
  an inference for a customer fact (§68).
* **Gaps are printed, not hidden.** A draft SOW says it is a draft, on the first
  page, with the reasons.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

BRAND = colors.HexColor("#0e7f8c")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#64748b")
RULE = colors.HexColor("#dfe5ee")

PROVENANCE_COLOR = {
    "CUSTOMER_DECISION": colors.HexColor("#0a7d63"),
    "FACT": colors.HexColor("#0e7f8c"),
    "AI_INFERENCE": colors.HexColor("#1769e0"),
    "RECOMMENDATION": colors.HexColor("#7c3aed"),
    "ASSUMPTION": colors.HexColor("#b45309"),
    "UNKNOWN": colors.HexColor("#b42318"),
}

#: Reports the platform can produce, and the artifacts each one draws on (§29).
REPORTS: Dict[str, Dict[str, Any]] = {
    "discovery": {"title": "Discovery Report", "artifacts": ["discovery", "question_set"]},
    "assessment": {"title": "Current-State Assessment", "artifacts": ["assessment"]},
    "requirements": {"title": "Requirements Catalogue", "artifacts": ["requirements"]},
    "platform": {"title": "Platform Decision", "artifacts": ["platform_decision", "platform_options"]},
    "architecture": {"title": "Solution Architecture", "artifacts": ["architecture"]},
    "data": {"title": "Data Design", "artifacts": ["data_design", "metadata"]},
    "governance": {"title": "Governance & Compliance", "artifacts": ["governance"]},
    "engineering": {"title": "Engineering Plan", "artifacts": ["engineering_plan", "work_packages"]},
    "estimation": {"title": "Effort & Automation", "artifacts": ["estimate"]},
    "sow": {"title": "Statement of Work", "artifacts": ["sow"]},
    "testing": {"title": "Test Plan", "artifacts": ["test_plan"]},
    "deployment": {"title": "Deployment Plan", "artifacts": ["deployment_plan"]},
    "handover": {"title": "Handover Pack", "artifacts": ["handover"]},
}


def _styles() -> Dict[str, ParagraphStyle]:
    s = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=s["Title"], fontSize=22, leading=26,
                                textColor=INK, spaceAfter=4, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("st", parent=s["Normal"], fontSize=10.5,
                                   textColor=MUTED, spaceAfter=14),
        "h2": ParagraphStyle("h2", parent=s["Heading2"], fontSize=13, leading=16,
                             textColor=BRAND, spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=s["Heading3"], fontSize=11, leading=14,
                             textColor=INK, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("b", parent=s["Normal"], fontSize=9.5, leading=13.5,
                               textColor=INK, spaceAfter=4),
        "small": ParagraphStyle("sm", parent=s["Normal"], fontSize=8, leading=11,
                                textColor=MUTED),
        "warn": ParagraphStyle("w", parent=s["Normal"], fontSize=10, leading=14,
                               textColor=colors.HexColor("#b42318"), spaceAfter=8),
        "bullet": ParagraphStyle("bu", parent=s["Normal"], fontSize=9.5, leading=13.5,
                                 textColor=INK, leftIndent=10, bulletIndent=2, spaceAfter=2),
    }


def _esc(text: Any) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _chrome(canvas, doc, project_name: str, title: str) -> None:
    """Header rule and footer, drawn on every page."""
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(BRAND)
    canvas.setLineWidth(2)
    canvas.line(18 * mm, h - 16 * mm, w - 18 * mm, h - 16 * mm)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.setFillColor(BRAND)
    canvas.drawString(18 * mm, h - 14 * mm, "ELITEINTELIA INTELLIGENCE FACTORY")
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(w - 18 * mm, h - 14 * mm, _esc(project_name)[:70])

    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(18 * mm, 10 * mm, f"{title} · generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    canvas.drawRightString(w - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _kv_table(rows: List[List[str]], widths=(52 * mm, 116 * mm)) -> Table:
    t = Table(rows, colWidths=list(widths), hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
    ]))
    return t


def _statement_table(statements: List[dict], st: Dict[str, ParagraphStyle]) -> Table:
    """Statements with their provenance carried into the document (§68)."""
    rows = [[Paragraph("<b>Ref</b>", st["small"]), Paragraph("<b>Statement</b>", st["small"]),
             Paragraph("<b>Provenance</b>", st["small"])]]
    for s in statements:
        prov = s.get("provenance", "AI_INFERENCE")
        colour = PROVENANCE_COLOR.get(prov, MUTED)
        rows.append([
            Paragraph(_esc(s.get("ref") or "—"), st["small"]),
            Paragraph(_esc(s.get("text", ""))[:400], st["body"]),
            # hexval() yields "0x0e7f8c"; reportlab's font tag needs "#0e7f8c".
            Paragraph(f'<font color="#{colour.hexval()[2:]}"><b>{prov.replace("_", " ")}</b></font>',
                      st["small"]),
        ])
    t = Table(rows, colWidths=[16 * mm, 118 * mm, 34 * mm], hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _render_value(value: Any, st: Dict[str, ParagraphStyle], flow: List) -> None:
    """Render arbitrary artifact content without assuming its shape."""
    if value is None or value == "":
        flow.append(Paragraph("<i>Not established.</i>", st["small"]))
    elif isinstance(value, str):
        flow.append(Paragraph(_esc(value)[:4000], st["body"]))
    elif isinstance(value, (int, float, bool)):
        flow.append(Paragraph(_esc(value), st["body"]))
    elif isinstance(value, list):
        if not value:
            flow.append(Paragraph("<i>None recorded.</i>", st["small"]))
        for item in value[:40]:
            if isinstance(item, dict):
                text = " · ".join(f"{k}: {v}" for k, v in item.items()
                                  if v not in (None, "", [], {}))
            else:
                text = str(item)
            flow.append(Paragraph(f"• {_esc(text)[:600]}", st["bullet"]))
        if len(value) > 40:
            flow.append(Paragraph(f"…and {len(value) - 40} more", st["small"]))
    elif isinstance(value, dict):
        rows = []
        for k, v in list(value.items())[:30]:
            if isinstance(v, (dict, list)):
                v = json.dumps(v)[:220]
            rows.append([_esc(k).replace("_", " "), Paragraph(_esc(v)[:600], st["body"])])
        if rows:
            flow.append(_kv_table(rows))


def build_report(kind: str, project: Dict[str, Any], artifacts: Dict[str, Any],
                 statements: Optional[List[dict]] = None,
                 degraded_note: str = "") -> bytes:
    """Render one stage report as a PDF."""
    spec = REPORTS.get(kind, {"title": kind.replace("_", " ").title(), "artifacts": [kind]})
    title = spec["title"]
    st = _styles()
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=22 * mm, bottomMargin=20 * mm,
        title=f"{title} — {project.get('name', '')}", author="EliteInteliA Intelligence Factory")

    flow: List[Any] = [
        Paragraph(_esc(title), st["title"]),
        Paragraph(f"{_esc(project.get('name', 'Project'))} · "
                  f"{_esc(project.get('domain') or 'domain not set')} · "
                  f"canonical version {project.get('version', 1)}", st["subtitle"]),
    ]

    # A document generated without AI enrichment must say so on page one.
    if degraded_note:
        flow.append(Paragraph(f"<b>Note:</b> {_esc(degraded_note)}", st["warn"]))

    if project.get("intent"):
        flow += [Paragraph("Business intent", st["h2"]),
                 Paragraph(_esc(project["intent"]), st["body"])]

    # SOW leads with issuability, because an incomplete SOW must not be issued.
    sow = artifacts.get("sow")
    if kind == "sow" and isinstance(sow, dict):
        c = sow.get("completeness", {})
        if not sow.get("issuable", False):
            flow.append(Paragraph(
                f"<b>DRAFT — NOT ISSUABLE.</b> {_esc(c.get('reason', ''))}", st["warn"]))
        flow.append(_kv_table([
            ["Sections complete", f"{c.get('complete_count', 0)} of {c.get('total_sections', 0)}"],
            ["Open questions", str(c.get("open_questions", 0))],
            ["Status", "Ready to issue" if sow.get("issuable") else "Draft"],
        ]))
        for key, value in (sow.get("sections") or {}).items():
            flow.append(Paragraph(_esc(key.replace("_", " ").title()), st["h2"]))
            _render_value(value, st, flow)
        if sow.get("open_questions"):
            flow += [PageBreak(), Paragraph("Open questions — customer input required", st["h2"])]
            for q in sow["open_questions"]:
                flow.append(Paragraph(f"• {_esc(q)}", st["bullet"]))
        return _finish(doc, flow, buf, project, title)

    # Generic artifact rendering for every other report.
    for name in spec["artifacts"]:
        content = artifacts.get(name)
        if content is None:
            continue
        flow.append(Paragraph(_esc(name.replace("_", " ").title()), st["h2"]))
        if isinstance(content, dict):
            mode = content.get("generation_mode", "")
            if mode and mode != "ai":
                flow.append(Paragraph(
                    "Produced without AI enrichment — evidence-only content.", st["small"]))
            for key, value in content.items():
                if key in ("generation_mode", "reason"):
                    continue
                flow.append(Paragraph(_esc(key.replace("_", " ").title()), st["h3"]))
                _render_value(value, st, flow)
        else:
            _render_value(content, st, flow)

    if statements:
        flow += [PageBreak(),
                 Paragraph("Evidence and provenance", st["h2"]),
                 Paragraph("Every statement below carries how it is known. Items marked "
                           "UNKNOWN require customer input before they can be relied upon.",
                           st["small"]),
                 Spacer(1, 6),
                 _statement_table(statements[:120], st)]

    return _finish(doc, flow, buf, project, title)


def _finish(doc, flow, buf, project, title) -> bytes:
    if len(flow) <= 2:
        flow.append(Paragraph(
            "No content has been generated for this stage yet. Run the stage to populate it.",
            _styles()["body"]))
    draw = lambda c, d: _chrome(c, d, project.get("name", ""), title)  # noqa: E731
    doc.build(flow, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()


def available_reports(artifact_kinds: set) -> List[dict]:
    """Which reports can be produced from what currently exists."""
    out = []
    for kind, spec in REPORTS.items():
        present = [a for a in spec["artifacts"] if a in artifact_kinds]
        out.append({"kind": kind, "title": spec["title"],
                    "available": bool(present), "uses": spec["artifacts"],
                    "present": present})
    return out
