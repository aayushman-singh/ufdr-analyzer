// Cross-case entity link-graph API client.
// Calls the provenance-cited link-graph endpoints. Errors are surfaced, never
// swallowed — a forensic surface must not silently show a partial graph.
//
// These endpoints require an authenticated owner: every request carries the
// bearer token (see lib/auth). Without one the server returns 401, which is
// surfaced to the user as an error (prompting login) rather than hidden.
import { authedFetch } from "./auth"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export type EntityType = "phone" | "email" | "other"

export interface EdgeCitation {
  run_id: string
  source_table: "message" | "call"
  row_id: string
  timestamp: string | null
}

export interface LinkNode {
  id: string
  type: EntityType
  redacted: boolean
  degree: number
  cases: string[]
  case_count: number
  value: string | null // null when redacted (cross-case PII)
  label: string | null
  hops: number | null
}

export interface LinkEdge {
  source: string // undirected endpoint (not a from-direction)
  target: string
  weight: number // true total interaction count (== total citations)
  citations_shown: number
  citations_truncated: boolean
  citations: EdgeCitation[] // up to the server cap
}

export interface LinkGraphResponse {
  run_ids: string[]
  seed: string | null
  seed_id: string | null
  seed_found: boolean
  max_hops: number | null
  window_start: string | null
  window_end: string | null
  excluded_events: number
  node_count: number
  edge_count: number
  nodes: LinkNode[]
  edges: LinkEdge[]
}

export interface LinkGraphParams {
  runIds: string[]
  seed?: string
  hops?: number
  start?: string // ISO instant
  end?: string
}

function buildQuery(params: LinkGraphParams): string {
  const q = new URLSearchParams()
  for (const id of params.runIds) q.append("run_ids", id)
  if (params.seed) q.set("seed", params.seed)
  if (params.hops !== undefined) q.set("hops", String(params.hops))
  if (params.start) q.set("start", params.start)
  if (params.end) q.set("end", params.end)
  return q.toString()
}

export async function getLinkGraph(
  params: LinkGraphParams,
): Promise<LinkGraphResponse> {
  const url = `${API_BASE_URL}/link-graph?${buildQuery(params)}`
  const res = await authedFetch(url, {
    headers: { Accept: "application/json" },
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => "")
    throw new Error(
      `Link-graph request failed: ${res.status} ${res.statusText}` +
        (detail ? ` — ${detail}` : ""),
    )
  }
  return res.json() as Promise<LinkGraphResponse>
}

// Download a signed, court-defensible export (JSON artifact or PDF summary).
export async function exportLinkGraph(
  params: LinkGraphParams,
  format: "json" | "pdf",
): Promise<Blob> {
  const res = await authedFetch(`${API_BASE_URL}/link-graph/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_ids: params.runIds,
      seed: params.seed ?? null,
      hops: params.hops ?? 2,
      start: params.start ?? null,
      end: params.end ?? null,
      format,
    }),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => "")
    throw new Error(
      `Export failed: ${res.status} ${res.statusText}` +
        (detail ? ` — ${detail}` : ""),
    )
  }
  return res.blob()
}
