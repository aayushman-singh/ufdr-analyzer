// Query Plan API Service
// Calls the auditable NL -> QueryPlan IR -> SQL -> cited results flow.
import { authedFetch } from "./auth"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export type PlannerKind = "llm" | "stub"
export type MatchMode = "any" | "all"

export interface QueryPredicate {
  field: string
  op: string
  values: string[]
}

export interface QueryEntity {
  type: string
  value: string
}

export interface QueryTimeRange {
  start?: string | null
  end?: string | null
}

export interface QuerySort {
  field?: string
  direction?: string
  [key: string]: unknown
}

export interface QueryPlan {
  targets: string[]
  predicates: QueryPredicate[]
  match: MatchMode
  time_range: QueryTimeRange | null
  entities: QueryEntity[]
  sort: QuerySort
  limit: number
  rationale: string
}

export interface ResultCitation {
  source_table: string
  row_id: string
  column: string
  matched_value: string
  snippet: string
  char_start: number
  char_end: number
}

export interface ResultRow {
  source_table: string
  row_id: string
  event_time: string | null
  preview: string
  citations: ResultCitation[]
}

export interface QueryPlanRequest {
  question: string
  run_id: string
  context?: Record<string, unknown>
}

export interface QueryPlanResponse {
  question: string
  planner: PlannerKind
  plan: QueryPlan
  sql: string
  total: number
  rows: ResultRow[]
}

export interface QueryPlanPreviewResponse {
  question: string
  planner: PlannerKind
  plan: QueryPlan
  sql: string
  targets: string[]
}

async function postJson<T>(endpoint: string, body: QueryPlanRequest): Promise<T> {
  const response = await authedFetch(`${API_BASE_URL}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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

// Execute the full flow: NL -> plan -> SQL -> cited results.
export function runQueryPlan(body: QueryPlanRequest): Promise<QueryPlanResponse> {
  return postJson<QueryPlanResponse>("/query/plan", body)
}

// Build the plan + SQL without executing it.
export function previewQueryPlan(body: QueryPlanRequest): Promise<QueryPlanPreviewResponse> {
  return postJson<QueryPlanPreviewResponse>("/query/plan/preview", body)
}
