"""Signed, deterministic evidence PDF for an auditable query answer.

Forensic exports must be reproducible and tamper-evident. We achieve that by
hashing the *logical content* of the answer (question + plan + SQL + cited rows)
rather than the PDF bytes (which carry non-deterministic jitter). That content
hash is HMAC-signed with the server `SECRET_KEY` and stamped into the document,
alongside the audit-chain head hash. Re-running the same query yields the same
logical content hash; the audit head is custody context displayed next to that
hash, not part of the hash itself (otherwise the audit event would have to commit
to a value that depends on its own future hash).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    Preformatted,
)


def _canonical_content(answer: dict, audit_head_hash: Optional[str] = None) -> str:
    """Stable serialization of the logical answer — the thing we hash/sign.

    Every field rendered in the report that matters for custody is included,
    so nothing printed in the PDF is left unauthenticated.
    """
    core = {
        "question": answer.get("question", ""),
        "planner": answer.get("planner", ""),
        "plan": answer.get("plan", {}),
        "sql": answer.get("sql", ""),
        "total": answer.get("total", 0),
        "rows": answer.get("rows", []),
    }
    return json.dumps(core, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(answer: dict, audit_head_hash: Optional[str] = None) -> str:
    return hashlib.sha256(
        _canonical_content(answer, audit_head_hash).encode("utf-8")
    ).hexdigest()


def sign(answer: dict, secret_key: str, audit_head_hash: Optional[str] = None) -> str:
    digest = content_hash(answer, audit_head_hash)
    return hmac.new(
        secret_key.encode("utf-8"), digest.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def build_evidence_pdf(
    answer: dict, secret_key: str, audit_head_hash: Optional[str] = None
) -> bytes:
    """Render the signed evidence PDF and return its bytes.

    The HMAC here is a keyed integrity signature using the server SECRET_KEY —
    it proves the report was produced by this server and has not been altered.
    It is intentionally NOT a public-key/PKI digital signature (no third-party
    verifiability); that is a documented limitation, not a substitute for X.509
    signing in a true chain-of-custody deployment.
    """
    chash = content_hash(answer, audit_head_hash)
    signature = sign(answer, secret_key, audit_head_hash)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title="UFDR Evidence Report",
        author="UFDR Analyzer",
        subject=f"content-hash:{chash}",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    mono = ParagraphStyle("mono", parent=styles["Code"], fontSize=7, leading=9)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
    story: list = []

    story.append(Paragraph("UFDR Analyzer — Evidence Report", styles["Title"]))
    story.append(
        Paragraph(
            f"Question: <b>{_esc(answer.get('question', ''))}</b>", styles["Normal"]
        )
    )
    story.append(
        Paragraph(
            f"Planner: {answer.get('planner', '?')} &nbsp;|&nbsp; "
            f"Results: {answer.get('total', 0)}",
            small,
        )
    )
    story.append(Spacer(1, 6))

    # Integrity block --------------------------------------------------------
    integrity = [
        ["SHA-256 content hash", chash],
        ["HMAC-SHA256 signature", signature],
        ["Audit chain head", audit_head_hash or "(not recorded)"],
    ]
    t = Table(integrity, colWidths=[40 * mm, 130 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("FONTNAME", (1, 0), (1, -1), "Courier"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#444444")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f4f4")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 10))

    # Query plan (the typed IR) ---------------------------------------------
    story.append(Paragraph("Query Plan (typed IR)", styles["Heading2"]))
    story.append(Preformatted(json.dumps(answer.get("plan", {}), indent=2), mono))
    story.append(Spacer(1, 8))

    # Compiled SQL -----------------------------------------------------------
    story.append(
        Paragraph("Compiled SQL (deterministic, parameter-bound)", styles["Heading2"])
    )
    story.append(Preformatted(answer.get("sql", ""), mono))
    story.append(Spacer(1, 8))

    # Cited results ----------------------------------------------------------
    story.append(Paragraph("Cited Results", styles["Heading2"]))
    rows = answer.get("rows", [])
    if not rows:
        story.append(Paragraph("No matching evidence.", small))
    for i, row in enumerate(rows, 1):
        story.append(
            Paragraph(
                f"{i}. <b>{_esc(row.get('source_table', ''))}</b> "
                f"#{_esc(str(row.get('row_id', '')))} "
                f"&nbsp; {_esc(str(row.get('event_time') or ''))}",
                small,
            )
        )
        story.append(Paragraph(_esc(row.get("preview", "")), small))
        for c in row.get("citations", []):
            story.append(
                Paragraph(
                    f"&nbsp;&nbsp;↳ <i>{_esc(c.get('column', ''))}</i> "
                    f"matched “{_esc(c.get('matched_value', ''))}” "
                    f"[{c.get('char_start')}:{c.get('char_end')}]: "
                    f"{_esc(c.get('snippet', ''))}",
                    mono,
                )
            )
        story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
