"""Temporal pattern & anomaly detection over a run's communications.

An investigator does not want a thousand rows — they want "what changed, and
when". This service derives behavioural findings from message + call timestamps:
volume spikes, late-night activity, communication cessation/drop-off, sustained
bursts, and the sudden emergence of a new contact. Every finding is **cited**:
it carries the ids of the underlying events, so a claim like "activity ceased
after 2024-03-04" is traceable to the rows that prove it.

Pure and deterministic — same data in, same findings out (thresholds are fixed
constants, outputs are sorted). Testable on SQLite; no heavy deps, no LLM.
A separate deterministic narrator turns the findings into one English paragraph.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from db_setup import Call, Message

# Detection thresholds — explicit so the output is reproducible and explainable.
_SPIKE_Z = 2.0            # std-devs above mean daily volume to call a "spike"
_SPIKE_MIN_EVENTS = 5     # ignore spikes below this absolute volume
_LATE_NIGHT_START = 0     # hours [0,5) are "late night"
_LATE_NIGHT_END = 5
_LATE_NIGHT_RATIO = 0.25  # flag if >= 25% of events are late-night
_LATE_NIGHT_MIN = 6       # ...and there are at least this many late-night events
_CESSATION_GAP_DAYS = 14  # trailing silence (vs span end) that counts as cessation
_DROP_WINDOW = 7          # days each side of a change-point
_DROP_RATIO = 0.6         # >= 60% relative drop after a change-point
_BURST_MIN_DAYS = 3       # consecutive above-mean days to be a "burst"
_EMERGENCE_MIN_EVENTS = 8 # new contact must reach this volume to be notable
_MAX_CITATIONS = 25


@dataclass
class Citation:
    source_table: str
    row_id: str


@dataclass
class Finding:
    type: str           # spike | late_night | cessation | drop | burst | new_contact
    severity: str       # low | medium | high
    title: str
    description: str
    dates: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    citations: list[Citation] = field(default_factory=list)


@dataclass
class _Event:
    kind: str   # "message" | "call"
    id: str
    ts: datetime
    a: str | None
    b: str | None


@dataclass
class PatternReport:
    run_id: str
    span_start: str | None
    span_end: str | None
    total_events: int
    daily_series: list[dict]
    findings: list[Finding]
    narrative: str

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "total_events": self.total_events,
            "daily_series": self.daily_series,
            "findings": [
                {
                    "type": f.type, "severity": f.severity, "title": f.title,
                    "description": f.description, "dates": f.dates, "stats": f.stats,
                    "citations": [c.__dict__ for c in f.citations],
                }
                for f in self.findings
            ],
            "narrative": self.narrative,
        }


class AnalyticsService:
    def __init__(self, session: Session):
        self.session = session

    def _load_events(self, run_id) -> list[_Event]:
        events: list[_Event] = []
        for m in self.session.exec(select(Message).where(Message.run_id == run_id)).all():
            if m.timestamp is not None:
                events.append(_Event("message", str(m.id), m.timestamp, m.sender, m.receiver))
        for c in self.session.exec(select(Call).where(Call.run_id == run_id)).all():
            if c.timestamp is not None:
                events.append(_Event("call", str(c.id), c.timestamp, c.caller, c.receiver))
        events.sort(key=lambda e: (e.ts, e.kind, e.id))
        return events

    def analyze(self, run_id) -> PatternReport:
        events = self._load_events(run_id)
        if not events:
            return PatternReport(str(run_id), None, None, 0, [], [],
                                 "No communication activity was found for this run.")

        by_day: dict[date, list[_Event]] = defaultdict(list)
        for e in events:
            by_day[e.ts.date()].append(e)

        span_start, span_end = events[0].ts.date(), events[-1].ts.date()
        series = self._dense_series(by_day, span_start, span_end)

        findings: list[Finding] = []
        findings += self._spikes(by_day, series)
        findings += self._late_night(events)
        findings += self._cessation(events, span_end)
        findings += self._drop(series, by_day)
        findings += self._bursts(series, by_day)
        findings += self._new_contacts(events, span_start)

        # Stable ordering: severity desc, then type, then first date.
        sev_rank = {"high": 0, "medium": 1, "low": 2}
        findings.sort(key=lambda f: (sev_rank.get(f.severity, 3), f.type, f.dates[:1]))

        return PatternReport(
            run_id=str(run_id),
            span_start=span_start.isoformat(),
            span_end=span_end.isoformat(),
            total_events=len(events),
            daily_series=[{"date": d.isoformat(), "messages": mc[0], "calls": mc[1],
                           "total": mc[0] + mc[1]} for d, mc in series],
            findings=findings,
            narrative=narrate(findings, span_start, span_end, len(events)),
        )

    # -- detectors ---------------------------------------------------------
    def _dense_series(self, by_day, start: date, end: date) -> list[tuple[date, tuple[int, int]]]:
        out: list[tuple[date, tuple[int, int]]] = []
        d = start
        while d <= end:
            evs = by_day.get(d, [])
            msgs = sum(1 for e in evs if e.kind == "message")
            calls = sum(1 for e in evs if e.kind == "call")
            out.append((d, (msgs, calls)))
            d += timedelta(days=1)
        return out

    def _spikes(self, by_day, series) -> list[Finding]:
        totals = [m + c for _, (m, c) in series]
        if len(totals) < 3:
            return []
        mean = statistics.fmean(totals)
        std = statistics.pstdev(totals)
        if std == 0:
            return []
        out: list[Finding] = []
        for d, (m, c) in series:
            vol = m + c
            if vol < _SPIKE_MIN_EVENTS:
                continue
            z = (vol - mean) / std
            if z >= _SPIKE_Z:
                evs = by_day.get(d, [])
                out.append(Finding(
                    type="spike",
                    severity="high" if z >= 3 else "medium",
                    title=f"Communication spike on {d.isoformat()}",
                    description=(f"{vol} events on {d.isoformat()} — {z:.1f}σ above the "
                                f"daily mean of {mean:.1f}."),
                    dates=[d.isoformat()],
                    stats={"volume": vol, "z_score": round(z, 2),
                           "daily_mean": round(mean, 2)},
                    citations=[Citation(e.kind, e.id) for e in evs[:_MAX_CITATIONS]],
                ))
        return out

    def _late_night(self, events) -> list[Finding]:
        late = [e for e in events
                if _LATE_NIGHT_START <= e.ts.hour < _LATE_NIGHT_END]
        if len(late) < _LATE_NIGHT_MIN:
            return []
        ratio = len(late) / len(events)
        if ratio < _LATE_NIGHT_RATIO:
            return []
        days = sorted({e.ts.date().isoformat() for e in late})
        return [Finding(
            type="late_night",
            severity="medium",
            title="Elevated late-night activity",
            description=(f"{len(late)} of {len(events)} events ({ratio:.0%}) occurred "
                         f"between 00:00–05:00 across {len(days)} day(s)."),
            dates=days[:10],
            stats={"late_night_events": len(late), "ratio": round(ratio, 3)},
            citations=[Citation(e.kind, e.id) for e in late[:_MAX_CITATIONS]],
        )]

    def _cessation(self, events, span_end: date) -> list[Finding]:
        last = events[-1].ts.date()
        gap = (span_end - last).days
        # span_end == last by construction, so detect cessation relative to the
        # *bulk* end: find the last day carrying >=2 events and measure trailing gap.
        active_days = sorted({e.ts.date() for e in events})
        if len(active_days) < 3:
            return []
        last_active = active_days[-1]
        # trailing silence between the penultimate burst and the true end:
        gap = (last_active - active_days[-2]).days
        if gap < _CESSATION_GAP_DAYS:
            return []
        return [Finding(
            type="cessation",
            severity="high",
            title=f"Communication gap of {gap} days",
            description=(f"After {active_days[-2].isoformat()} there was no activity for "
                         f"{gap} days until {last_active.isoformat()} — a sustained break."),
            dates=[active_days[-2].isoformat(), last_active.isoformat()],
            stats={"gap_days": gap},
            citations=[],
        )]

    def _drop(self, series, by_day) -> list[Finding]:
        totals = [t for _, (m, c) in series for t in [m + c]]
        n = len(totals)
        if n < 2 * _DROP_WINDOW:
            return []
        out: list[Finding] = []
        best = None
        for i in range(_DROP_WINDOW, n - _DROP_WINDOW + 1):
            before = statistics.fmean(totals[i - _DROP_WINDOW:i])
            after = statistics.fmean(totals[i:i + _DROP_WINDOW])
            if before <= 0:
                continue
            drop = (before - after) / before
            if drop >= _DROP_RATIO and (best is None or drop > best[1]):
                best = (i, drop, before, after)
        if best:
            i, drop, before, after = best
            change_date = series[i][0]
            out.append(Finding(
                type="drop",
                severity="high" if drop >= 0.8 else "medium",
                title=f"Activity dropped {drop:.0%} after {change_date.isoformat()}",
                description=(f"Daily volume fell from ~{before:.1f} to ~{after:.1f} "
                            f"({drop:.0%}) around {change_date.isoformat()}."),
                dates=[change_date.isoformat()],
                stats={"before_mean": round(before, 2), "after_mean": round(after, 2),
                       "drop_ratio": round(drop, 3)},
                citations=[],
            ))
        return out

    def _bursts(self, series, by_day) -> list[Finding]:
        totals = [m + c for _, (m, c) in series]
        if len(totals) < _BURST_MIN_DAYS:
            return []
        mean = statistics.fmean(totals)
        if mean <= 0:
            return []
        out: list[Finding] = []
        run_days: list[date] = []
        for d, (m, c) in series:
            if (m + c) > mean:
                run_days.append(d)
            else:
                self._emit_burst(run_days, by_day, out)
                run_days = []
        self._emit_burst(run_days, by_day, out)
        return out

    def _emit_burst(self, run_days, by_day, out) -> None:
        if len(run_days) < _BURST_MIN_DAYS:
            return
        evs = [e for d in run_days for e in by_day.get(d, [])]
        out.append(Finding(
            type="burst",
            severity="low",
            title=f"{len(run_days)}-day activity burst from {run_days[0].isoformat()}",
            description=(f"Sustained above-average activity from {run_days[0].isoformat()} "
                        f"to {run_days[-1].isoformat()} ({len(evs)} events)."),
            dates=[run_days[0].isoformat(), run_days[-1].isoformat()],
            stats={"days": len(run_days), "events": len(evs)},
            citations=[Citation(e.kind, e.id) for e in evs[:_MAX_CITATIONS]],
        ))

    def _new_contacts(self, events, span_start: date) -> list[Finding]:
        first_seen: dict[str, date] = {}
        per_contact: dict[str, list[_Event]] = defaultdict(list)
        for e in events:
            for party in (e.a, e.b):
                if not party:
                    continue
                per_contact[party].append(e)
                if party not in first_seen or e.ts.date() < first_seen[party]:
                    first_seen[party] = e.ts.date()
        out: list[Finding] = []
        for party, evs in sorted(per_contact.items()):
            emerged = first_seen[party]
            # "New" = first appears at least a week into the timeline, then active.
            if (emerged - span_start).days >= 7 and len(evs) >= _EMERGENCE_MIN_EVENTS:
                out.append(Finding(
                    type="new_contact",
                    severity="medium",
                    title=f"New contact '{party}' emerged on {emerged.isoformat()}",
                    description=(f"'{party}' first appears on {emerged.isoformat()} "
                                f"({(emerged - span_start).days} days into the timeline) "
                                f"with {len(evs)} subsequent events."),
                    dates=[emerged.isoformat()],
                    stats={"first_seen": emerged.isoformat(), "events": len(evs)},
                    citations=[Citation(e.kind, e.id) for e in evs[:_MAX_CITATIONS]],
                ))
        return out


def narrate(findings: list[Finding], span_start: date, span_end: date,
            total_events: int) -> str:
    """Deterministic English summary of the findings (no LLM required)."""
    span_days = (span_end - span_start).days + 1
    head = (f"Across {span_days} day(s) ({span_start.isoformat()} → "
            f"{span_end.isoformat()}) the device shows {total_events} communication "
            f"event(s).")
    if not findings:
        return head + " No notable temporal anomalies were detected."

    high = [f for f in findings if f.severity == "high"]
    parts: list[str] = [head]
    if high:
        parts.append("Most notably: " + "; ".join(f.title for f in high[:3]) + ".")
    rest = [f for f in findings if f.severity != "high"]
    if rest:
        parts.append("Also flagged: " + "; ".join(f.title for f in rest[:4]) + ".")
    parts.append("Each finding is backed by the underlying event citations.")
    return " ".join(parts)
