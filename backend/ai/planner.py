"""NL question -> validated `QueryPlan`.

Two planners, chosen explicitly (never silently):

* **llm** — the default. Calls an OpenAI-compatible endpoint constrained to emit
  JSON, then validates it against `QueryPlan`. On a validation error the error
  text is fed back once for self-correction; a second failure raises loudly. The
  model only ever produces the IR — never SQL.

* **stub** — a deterministic, rule-based planner used ONLY when `DEMO_MODE=1`
  and no LLM key is configured. It is logged loudly as a stub on every call so
  no one mistakes its output for a real model's. This is the one sanctioned
  "alternative behaviour" (see project no-fallback rule): explicit, opt-in, loud.
"""
from __future__ import annotations

import json
import logging
import os
import re

from pydantic import ValidationError

from ai.query_plan import (
    Entity,
    FieldName,
    Match,
    Op,
    Predicate,
    QueryPlan,
    Target,
)

logger = logging.getLogger(__name__)

# Known app aliases -> canonical token used in the `app` predicate.
_APP_ALIASES = {
    "whatsapp": "whatsapp", "wa": "whatsapp",
    "instagram": "instagram", "insta": "instagram", "ig": "instagram",
    "telegram": "telegram", "signal": "signal", "snapchat": "snapchat",
    "snap": "snapchat", "messenger": "messenger", "facebook": "facebook",
    "chrome": "chrome",
}
_CRYPTO_TERMS = ["bitcoin", "btc", "ethereum", "eth", "usdt", "wallet", "crypto"]
_PHONE_RE = re.compile(r"\+?\d[\d\s\-]{6,}\d")


def plan_question(question: str, context: dict | None = None) -> tuple[QueryPlan, str]:
    """Return (plan, planner_name). Raises loudly if no planner can run."""
    use_stub = _stub_requested()
    if use_stub:
        logger.warning(
            "PLANNER=STUB: DEMO_MODE on with no LLM key — using the deterministic "
            "rule-based planner. Output is NOT from a language model."
        )
        return _stub_plan(question), "stub"
    return _llm_plan(question, context or {}), "llm"


def _stub_requested() -> bool:
    demo = os.getenv("DEMO_MODE", "0").lower() in ("1", "true", "yes")
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    return demo and not has_key


# --------------------------------------------------------------------------
# Deterministic stub planner
# --------------------------------------------------------------------------
def _stub_plan(question: str) -> QueryPlan:
    q = question.lower()
    targets: list[Target] = []
    predicates: list[Predicate] = []
    entities: list[Entity] = []

    # App-specific?
    for alias, canon in _APP_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", q):
            targets.append(Target.aleapp_artifacts)
            predicates.append(Predicate(field=FieldName.app, op=Op.contains, values=[canon]))
            entities.append(Entity(type="app", value=canon))
            break

    # Calls?
    if re.search(r"\bcalls?\b|phoned|dialed|rang", q):
        targets.append(Target.calls)

    # Crypto?
    crypto_hits = [t for t in _CRYPTO_TERMS if t in q]
    if crypto_hits:
        targets.append(Target.messages)
        predicates.append(Predicate(field=FieldName.text, op=Op.contains, values=crypto_hits))
        entities += [Entity(type="crypto", value=t) for t in crypto_hits]

    # Phone numbers mentioned?
    phones = [p.strip() for p in _PHONE_RE.findall(question)]
    if phones:
        predicates.append(Predicate(field=FieldName.participant, op=Op.contains, values=phones))
        entities += [Entity(type="phone", value=p) for p in phones]
        if Target.calls not in targets:
            targets.append(Target.calls)
        if Target.messages not in targets:
            targets.append(Target.messages)

    # Fallback content keywords (stopword-filtered) if nothing structured fired.
    if not predicates:
        words = [w for w in re.findall(r"[a-z0-9]{4,}", q) if w not in _STOPWORDS]
        if words:
            predicates.append(Predicate(field=FieldName.text, op=Op.contains, values=words[:6]))
            entities += [Entity(type="keyword", value=w) for w in words[:6]]

    if not targets:
        targets = [Target.messages, Target.aleapp_artifacts]

    # De-dup targets, preserve order.
    seen: set[Target] = set()
    targets = [t for t in targets if not (t in seen or seen.add(t))]

    return QueryPlan(
        targets=targets,
        predicates=predicates,
        match=Match.any,
        entities=entities,
        rationale=f"[stub] heuristic plan for: {question!r}",
    )


_STOPWORDS = {
    "show", "find", "list", "give", "from", "with", "that", "this", "what",
    "where", "when", "have", "they", "them", "were", "your", "about", "into",
    "messages", "message", "data", "please", "search", "between", "during",
}


# --------------------------------------------------------------------------
# LLM planner
# --------------------------------------------------------------------------
def _llm_plan(question: str, context: dict) -> QueryPlan:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No OPENAI_API_KEY configured and DEMO_MODE is off — cannot plan the "
            "query. Set OPENAI_API_KEY, or set DEMO_MODE=1 to use the stub planner."
        )
    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.getenv("LLM_MODEL", "anthropic/claude-3.5-sonnet")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    system = _system_prompt(context)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]

    last_error: Exception | None = None
    for attempt in range(2):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        raw = resp.choices[0].message.content
        try:
            data = json.loads(raw)
            return QueryPlan.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            logger.warning("LLM plan invalid (attempt %d): %s", attempt + 1, e)
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    "That did not validate against the QueryPlan schema. Error:\n"
                    f"{e}\nReturn corrected JSON only."
                ),
            })

    raise RuntimeError(f"LLM failed to produce a valid QueryPlan after 2 attempts: {last_error}")


def _system_prompt(context: dict) -> str:
    schema = json.dumps(QueryPlan.model_json_schema(), indent=2)
    ctx = f"\n\nRun context:\n{json.dumps(context, indent=2)}" if context else ""
    return (
        "You translate an investigator's natural-language question about Android "
        "forensic data into a QueryPlan JSON object. Output ONLY JSON conforming "
        "to this JSON Schema — no SQL, no prose.\n\n"
        "Targets: messages (SMS), calls, contacts, media, aleapp_artifacts "
        "(per-app data: WhatsApp/Instagram/Chrome/etc). For app-specific questions "
        "use aleapp_artifacts with an `app` predicate. Use `text` predicates for "
        "content keywords, `participant` for phone numbers/handles. Set `match` to "
        "\"all\" only when every predicate must hold.\n\n"
        f"JSON Schema:\n{schema}{ctx}"
    )
