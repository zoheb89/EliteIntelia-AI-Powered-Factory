"""Structured extraction from spreadsheet evidence (spec §8, §9).

RFI/RFP trackers are the most common and most structured evidence a bid team
holds — a table where each row is a requirement. Prose extraction misses them
entirely, because a cell reading "Real-time parcel tracking" contains no modal
verb for a sentence matcher to catch.

This module reads the CSV text produced by document extraction, recognises
requirement-shaped tables by their headers, and returns one structured
requirement per row with a citable `sheet!row` locator.

It is deliberately deterministic: a customer's own requirement list must be
reproduced exactly, never paraphrased by a model.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SHEET_MARKER = re.compile(r"^##\s*SHEET:\s*(.+)$", re.M)

#: Header names that identify the column holding the requirement itself.
TEXT_HEADERS = [
    "requirement", "requirements", "description", "question", "query",
    "specification", "spec", "item", "criteria", "criterion", "need",
    "capability", "feature", "functionality", "scope", "detail", "details",
    "ask", "clause", "statement", "expectation",
]
ID_HEADERS = ["id", "ref", "reference", "no", "no.", "number", "s.no", "sr", "sr.no",
              "item no", "req id", "requirement id", "sl", "sl.no", "#"]
CATEGORY_HEADERS = ["category", "type", "section", "area", "module", "domain",
                    "group", "theme", "classification", "discipline"]
PRIORITY_HEADERS = ["priority", "importance", "criticality", "mandatory", "must",
                    "weight", "mos", "compliance"]
RESPONSE_HEADERS = ["response", "answer", "reply", "comment", "comments", "remarks",
                    "status", "compliance status", "vendor response", "notes"]

#: A table needs a text column and at least this many usable rows to count.
MIN_ROWS = 2
MAX_ROWS = 400
MIN_TEXT_LEN = 8


@dataclass
class Requirement:
    text: str
    ref: str = ""
    category: str = ""
    priority: str = ""
    response: str = ""
    locator: str = ""
    answered: bool = False
    is_question: bool = False

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in ("", False) or k == "answered"}


@dataclass
class TableExtraction:
    sheet: str
    header: List[str]
    text_column: str
    requirements: List[Requirement] = field(default_factory=list)
    row_count: int = 0

    def to_dict(self) -> dict:
        return {"sheet": self.sheet, "header": self.header,
                "requirement_column": self.text_column, "rows": self.row_count,
                "requirements": [r.to_dict() for r in self.requirements]}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _match_header(header: List[str], candidates: List[str]) -> Optional[int]:
    """Index of the first column whose name matches one of `candidates`.

    Exact matches win over substring matches so a `Requirement ID` column is not
    mistaken for the requirement text itself.
    """
    lowered = [_norm(h).lower().strip(" :*#") for h in header]
    for i, h in enumerate(lowered):
        if h in candidates:
            return i
    for i, h in enumerate(lowered):
        if h and any(c in h for c in candidates):
            return i
    return None


#: An identifier cell: "RFI-001", "R12", "3.2", "7". Never a sentence.
ID_SHAPE = re.compile(r"^[A-Za-z]{0,8}[-_. ]?\d+(?:[.\-]\d+)*[a-zA-Z]?$")

#: Rows phrased as a request to the customer rather than a stated requirement.
QUESTION_OPENERS = (
    "please confirm", "please provide", "please identify", "please validate",
    "please clarify", "please specify", "please share", "please advise",
    "confirm ", "clarify ", "identify ", "specify ", "provide ", "validate ",
    "for each ", "if ", "what ", "which ", "who ", "when ", "where ", "how ",
)


def _median_len(values: List[str]) -> float:
    lengths = sorted(len(v) for v in values if v)
    if not lengths:
        return 0.0
    mid = len(lengths) // 2
    return float(lengths[mid] if len(lengths) % 2 else
                 (lengths[mid - 1] + lengths[mid]) / 2)


def _looks_like_ids(values: List[str]) -> bool:
    """True when a column's values read as identifiers, not prose."""
    present = [v for v in values if v]
    if not present:
        return False
    if _median_len(present) > 24:
        return False
    return sum(1 for v in present if ID_SHAPE.match(v)) >= max(1, len(present) * 0.6)


def is_question_row(text: str, answered: bool) -> bool:
    """A tracker row that asks the customer something still-unanswered.

    Recording these as evidenced requirements is what let a tracker of 41 open
    questions report as 41 established facts.
    """
    if answered:
        return False
    t = _norm(text).lower()
    return t.endswith("?") or t.startswith(QUESTION_OPENERS)


def split_sheets(text: str) -> List[Tuple[str, str]]:
    """Split extracted text into (sheet_name, csv_body) pairs."""
    if not text:
        return []
    markers = list(SHEET_MARKER.finditer(text))
    if not markers:
        return [("Sheet1", text)]
    out: List[Tuple[str, str]] = []
    for i, m in enumerate(markers):
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        out.append((m.group(1).strip(), text[start:end].strip()))
    return out


def _read_rows(body: str) -> List[List[str]]:
    try:
        rows = list(csv.reader(io.StringIO(body)))
    except csv.Error:
        return []
    return [r for r in rows if any(_norm(c) for c in r)]


def _find_header_row(rows: List[List[str]]) -> Optional[int]:
    """Locate the header row.

    Trackers frequently carry a title block above the real header, so the first
    non-empty row is not a safe assumption; the row that best matches known
    header names is used instead.
    """
    best, best_score = None, 0
    for i, row in enumerate(rows[:12]):
        cells = [_norm(c).lower().strip(" :*#") for c in row]
        score = sum(
            1 for c in cells if c and (
                c in TEXT_HEADERS or c in ID_HEADERS or c in CATEGORY_HEADERS
                or c in PRIORITY_HEADERS or c in RESPONSE_HEADERS
                or any(t in c for t in TEXT_HEADERS)))
        if score > best_score:
            best, best_score = i, score
    return best if best_score >= 1 else None


def extract_table(sheet: str, body: str) -> Optional[TableExtraction]:
    """Extract requirements from one sheet, or None if it is not a requirement table."""
    rows = _read_rows(body)
    if len(rows) < MIN_ROWS + 1:
        return None

    header_idx = _find_header_row(rows)
    if header_idx is None:
        return None
    header = [_norm(c) for c in rows[header_idx]]

    # A table has columns. Prose read line-by-line does not: every line becomes
    # a single cell, the loose header match fires on any line containing a word
    # like "scope" or "need", and each subsequent line — headings, wrapped
    # sentence fragments, arrows from a flow diagram — is captured as a
    # requirement. Structure is what separates a tracker from a paragraph.
    if sum(1 for c in header if c) < 2:
        return None
    body = rows[header_idx + 1:][:MAX_ROWS]
    multi_column = sum(1 for r in body if sum(1 for c in r if _norm(c)) >= 2)
    if not body or multi_column < max(MIN_ROWS, len(body) * 0.5):
        return None

    text_col = _match_header(header, TEXT_HEADERS)
    if text_col is None:
        return None

    id_col = _match_header(header, ID_HEADERS)
    cat_col = _match_header(header, CATEGORY_HEADERS)
    pri_col = _match_header(header, PRIORITY_HEADERS)
    resp_col = _match_header(header, RESPONSE_HEADERS)
    # A column cannot be both the requirement and its identifier.
    for name in ("id_col", "cat_col", "pri_col", "resp_col"):
        if locals()[name] == text_col:
            pass  # resolved below

    id_col = None if id_col == text_col else id_col
    cat_col = None if cat_col == text_col else cat_col
    pri_col = None if pri_col == text_col else pri_col
    resp_col = None if resp_col == text_col else resp_col

    def cell(row: List[str], idx: Optional[int]) -> str:
        if idx is None or idx >= len(row):
            return ""
        return _norm(row[idx])

    # Header names alone are not enough. A sheet whose label column is called
    # "Scope" and whose prose column is called "Position" would otherwise put
    # the sentence in `ref` and the label in `text`, inverting every row. Check
    # what the columns actually contain before trusting the names.
    body_rows = rows[header_idx + 1:][:MAX_ROWS]
    col_values = {i: [cell(r, i) for r in body_rows] for i in range(len(header))}

    if id_col is not None and not _looks_like_ids(col_values.get(id_col, [])):
        # Whatever this column holds, it is not an identifier. If it carries the
        # longest prose on the sheet, it is the requirement itself.
        if _median_len(col_values.get(id_col, [])) > _median_len(col_values.get(text_col, [])) * 2:
            if cat_col is None:
                cat_col = text_col
            text_col, id_col = id_col, None
        else:
            id_col = None

    # The requirement column should hold the sheet's substantive text. When the
    # name-matched column is a short label, prefer a clearly longer neighbour.
    text_median = _median_len(col_values.get(text_col, []))
    if text_median < 25:
        taken = {text_col, id_col, cat_col, pri_col, resp_col}
        longest = max((i for i in col_values if i not in taken),
                      key=lambda i: _median_len(col_values[i]), default=None)
        if longest is not None and _median_len(col_values[longest]) >= max(25.0, text_median * 2):
            if cat_col is None:
                cat_col = text_col
            text_col = longest

    requirements: List[Requirement] = []
    for offset, row in enumerate(rows[header_idx + 1:][:MAX_ROWS], start=1):
        text = cell(row, text_col)
        if len(text) < MIN_TEXT_LEN or text.lower() in {h.lower() for h in header}:
            continue
        response = cell(row, resp_col)
        requirements.append(Requirement(
            text=text[:600],
            ref=cell(row, id_col)[:40],
            category=cell(row, cat_col)[:80],
            priority=cell(row, pri_col)[:40],
            response=response[:300],
            locator=f"{sheet}!row{header_idx + 1 + offset}",
            answered=bool(response),
            is_question=is_question_row(text, bool(response)),
        ))

    if len(requirements) < MIN_ROWS:
        return None
    return TableExtraction(sheet=sheet, header=header,
                           text_column=header[text_col] if text_col < len(header) else "",
                           requirements=requirements, row_count=len(requirements))


def extract_documents(documents: List[dict]) -> Dict[str, Any]:
    """Mine every supplied document for requirement tables.

    `documents` are the stored records: {"name", "text", ...}.
    """
    tables: List[TableExtraction] = []
    for doc in documents or []:
        text = doc.get("text") or doc.get("extracted_text") or ""
        if not text:
            continue
        for sheet, body in split_sheets(text):
            table = extract_table(f"{doc.get('name', 'document')}::{sheet}", body)
            if table:
                tables.append(table)

    requirements = [r for t in tables for r in t.requirements]
    answered = sum(1 for r in requirements if r.answered)
    open_questions = sum(1 for r in requirements if r.is_question)
    categories: Dict[str, int] = {}
    for r in requirements:
        if r.category:
            categories[r.category] = categories.get(r.category, 0) + 1

    return {
        "tables": [t.to_dict() for t in tables],
        "requirements": [r.to_dict() for r in requirements],
        "requirement_count": len(requirements),
        "answered_count": answered,
        "unanswered_count": len(requirements) - answered,
        "open_question_count": open_questions,
        "stated_requirement_count": len(requirements) - open_questions,
        "categories": dict(sorted(categories.items(), key=lambda kv: -kv[1])),
        "found": bool(requirements),
    }


def summarize(extraction: Dict[str, Any]) -> str:
    """One honest sentence describing what was extracted."""
    if not extraction.get("found"):
        return ""
    n = extraction["requirement_count"]
    sheets = len(extraction["tables"])
    cats = len(extraction["categories"])
    parts = [f"{n} requirement rows extracted from {sheets} "
             f"requirement table{'s' if sheets != 1 else ''}"]
    if cats:
        parts.append(f"across {cats} categor{'ies' if cats != 1 else 'y'}")
    if extraction["unanswered_count"]:
        parts.append(f"{extraction['unanswered_count']} still unanswered")
    return ", ".join(parts) + "."
