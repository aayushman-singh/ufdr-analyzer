"""Signed, deterministic export of a cross-case entity link graph.

A graph put before a court must be reproducible and tamper-evident. As with the
evidence PDF, we hash the *logical content* of the graph (its nodes, edges, and
provenance citations) — not any rendered layout, which carries non-deterministic
jitter — and HMAC-sign that hash with the server `SECRET_KEY`, folding in the
audit-chain head so the chain-of-custody pointer cannot be edited post-hoc.

Re-running the same query over the same evidence yields the same content hash and
the same signature; anyone holding the key can recompute and verify both.

The signed JSON is the primary artifact (a graph's logical content is what must be
reproducible). A human-readable PDF summary is rendered for the *same* content hash
so an examiner has a printable, equally-authenticated view.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _canonical_content(graph: dict) -> str:
    """Stable serialization of the graph's logical content — the reproducible
    evidence identity.

    The audit-chain head is deliberately NOT folded in here: the content hash must
    be identical every time the same evidence + parameters are exported (that is
    what determinism means). The head is bound separately, by the signature, so a
    second export of the same graph still has the same content hash but a fresh,
    chain-anchored signature.
    """
    core = {
        "run_ids": sorted(graph.get("run_ids", [])),
        "seed": graph.get("seed"),
        "seed_id": graph.get("seed_id"),
        "max_hops": graph.get("max_hops"),
        "window_start": graph.get("window_start"),
        "window_end": graph.get("window_end"),
        "excluded_events": graph.get("excluded_events", 0),
        "nodes": graph.get("nodes", []),
        "edges": graph.get("edges", []),
    }
    return json.dumps(core, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(graph: dict) -> str:
    """Reproducible SHA-256 over the graph's logical content (head-independent)."""
    return hashlib.sha256(_canonical_content(graph).encode("utf-8")).hexdigest()


def sign(graph: dict, secret_key: str, audit_head_hash: Optional[str] = None) -> str:
    """HMAC over `content_hash || audit_head_hash` — binds the reproducible content
    identity to the chain-of-custody pointer at export time."""
    material = f"{content_hash(graph)}:{audit_head_hash or ''}"
    return hmac.new(
        secret_key.encode("utf-8"), material.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def signed_artifact(
    graph: dict, secret_key: str, audit_head_hash: Optional[str] = None
) -> dict:
    """The primary court artifact: the full graph plus its integrity envelope.

    `content_hash` is the reproducible evidence identity; `signature` additionally
    commits to `audit_head_hash`. The audit chain records this same `content_hash`,
    so the event and the artifact provably refer to the same graph.
    """
    return {
        "kind": "ufdr-link-graph",
        "version": 1,
        "content_hash": content_hash(graph),
        "signature": sign(graph, secret_key, audit_head_hash),
        "audit_head_hash": audit_head_hash or "",
        "graph": graph,
    }


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_graph_pdf(
    graph: dict, secret_key: str, audit_head_hash: Optional[str] = None
) -> bytes:
    """Render a signed PDF summary of the link graph and return its bytes.

    The HMAC here is a keyed integrity signature using the server SECRET_KEY — it
    proves the report was produced by this server and not altered. It is
    intentionally NOT a public-key/PKI signature (no third-party verifiability);
    that is a documented limitation, not a substitute for X.509 signing in a true
    chain-of-custody deployment.
    """
    chash = content_hash(graph)
    signature = sign(graph, secret_key, audit_head_hash)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title="CiteSpan Entity Link Graph",
        author="CiteSpan",
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

    story.append(Paragraph("CiteSpan — Entity Link Graph", styles["Title"]))
    seed = graph.get("seed")
    scope = (
        f"Seed: <b>{_esc(seed)}</b> &nbsp;|&nbsp; max hops: {graph.get('max_hops')}"
        if seed
        else "Scope: full graph (no seed)"
    )
    story.append(Paragraph(scope, styles["Normal"]))
    story.append(
        Paragraph(
            f"Cases: {len(graph.get('run_ids', []))} &nbsp;|&nbsp; "
            f"Nodes: {graph.get('node_count', len(graph.get('nodes', [])))} &nbsp;|&nbsp; "
            f"Edges: {graph.get('edge_count', len(graph.get('edges', [])))} &nbsp;|&nbsp; "
            f"Window: {graph.get('window_start') or '—'} → {graph.get('window_end') or '—'}",
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

    # Cases in scope ---------------------------------------------------------
    story.append(Paragraph("Cases in scope (run ids)", styles["Heading2"]))
    story.append(Preformatted("\n".join(graph.get("run_ids", [])) or "(none)", mono))
    story.append(Spacer(1, 8))

    # Entities ---------------------------------------------------------------
    story.append(Paragraph("Entities", styles["Heading2"]))
    for n in graph.get("nodes", []):
        if n.get("redacted"):
            ident = f"[redacted cross-case · {n.get('type')}] {n.get('id')[:16]}…"
        else:
            ident = f"{_esc(n.get('label') or n.get('value') or '')} ({n.get('type')})"
        story.append(
            Paragraph(
                f"• <b>{ident}</b> — degree {n.get('degree', 0)}, "
                f"in {n.get('case_count', 0)} case(s)"
                + (
                    f", {n['hops']} hop(s) from seed"
                    if n.get("hops") is not None
                    else ""
                ),
                small,
            )
        )
    story.append(Spacer(1, 8))

    # Relations + provenance -------------------------------------------------
    story.append(
        Paragraph("Relations (each cited to its source rows)", styles["Heading2"])
    )
    edges = graph.get("edges", [])
    if not edges:
        story.append(Paragraph("No relations in scope.", small))
    for e in edges:
        weight = e.get("weight", 0)
        shown = e.get("citations_shown", len(e.get("citations", [])))
        cite_note = (
            f"showing {shown} of {weight} source rows"
            if e.get("citations_truncated")
            else f"{weight} source row(s)"
        )
        story.append(
            Paragraph(
                f"{_esc(e.get('source')[:12])}… — {_esc(e.get('target')[:12])}… "
                f"&nbsp; weight {weight} ({cite_note})",
                small,
            )
        )
        for c in e.get("citations", []):
            story.append(
                Paragraph(
                    f"&nbsp;&nbsp;↳ run {_esc(c.get('run_id'))[:8]} · "
                    f"{_esc(c.get('source_table'))} #{_esc(c.get('row_id'))[:12]} · "
                    f"{_esc(c.get('timestamp') or '—')}",
                    mono,
                )
            )
        story.append(Spacer(1, 3))

    doc.build(story)
    return buf.getvalue()
