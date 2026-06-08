// Analytics API Service
// Calls the behavioural-pattern detection and cross-case correlation endpoints.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// ---- Patterns ----

export type FindingType =
  | "spike"
  | "late_night"
  | "cessation"
  | "drop"
  | "burst"
  | "new_contact"

export type Severity = "low" | "medium" | "high"

export interface DailyPoint {
  date: string
  messages: number
  calls: number
  total: number
}

export interface FindingCitation {
  source_table: string
  row_id: string
}

export interface Finding {
  type: FindingType
  severity: Severity
  title: string
  description: string
  dates: string[]
  stats: Record<string, unknown>
  citations: FindingCitation[]
}

export interface PatternsResponse {
  run_id: string
  span_start: string
  span_end: string
  total_events: number
  daily_series: DailyPoint[]
  findings: Finding[]
  narrative: string
}

// ---- Cross-case ----

export type IdentifierType = "phone" | "email"

export interface CrossCaseLink {
  identifier: string
  identifier_type: IdentifierType
  also_in_runs: string[]
  case_count: number
}

export interface CrossCaseLinksResponse {
  run_id: string
  link_count: number
  links: CrossCaseLink[]
}

export interface IdentifierLookupResponse {
  identifier: string
  identifier_hash: string
  runs: string[]
  count: number
}

async function getJson<T>(endpoint: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  })

  if (!response.ok) {
    // Surface the backend error text rather than swallowing it.
    const detail = await response.text().catch(() => "")
    throw new Error(
      `Request to ${endpoint} failed: ${response.status} ${response.statusText}` +
        (detail ? ` — ${detail}` : ""),
    )
  }

  return response.json() as Promise<T>
}

// Detect behavioural patterns (spikes, late-night activity, cessation, ...).
export function getPatterns(runId: string): Promise<PatternsResponse> {
  return getJson<PatternsResponse>(
    `/analytics/patterns?run_id=${encodeURIComponent(runId)}`,
  )
}

// Find identifiers in this run that also appear in other cases.
export function getCrossCaseLinks(runId: string): Promise<CrossCaseLinksResponse> {
  return getJson<CrossCaseLinksResponse>(
    `/cross-case/links?run_id=${encodeURIComponent(runId)}`,
  )
}

// Look up a single identifier across all cases (privacy-preserving salted hash).
export function lookupIdentifier(
  identifier: string,
): Promise<IdentifierLookupResponse> {
  return getJson<IdentifierLookupResponse>(
    `/cross-case/lookup?identifier=${encodeURIComponent(identifier)}`,
  )
}
