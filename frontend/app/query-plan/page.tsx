"use client"

import { useState } from "react"
import Link from "next/link"
import {
  Play,
  Eye,
  Loader2,
  AlertTriangle,
  FileText,
  Database,
  ListTree,
  Quote,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Seal } from "@/components/brand/Seal"
import { API_BASE_URL, authedFetch } from "@/lib/auth"
import {
  previewQueryPlan,
  runQueryPlan,
  type QueryPlanPreviewResponse,
  type QueryPlanResponse,
  type ResultCitation,
} from "@/lib/queryPlanApi"

const SAMPLE_QUESTIONS = [
  "Show me all WhatsApp messages mentioning a bank transfer",
  "Find calls with contacts flagged for fraud last month",
  "List documents that reference the codename 'Nightingale'",
]

// A preview response is a strict subset of a full run, so we can render
// the shared panels (plan + SQL) from either, and only show results when
// a full run produced rows.
type AnyResponse = QueryPlanResponse | QueryPlanPreviewResponse

function isFullRun(res: AnyResponse): res is QueryPlanResponse {
  return "rows" in res
}

// Split a snippet around the matched span so it can be highlighted inline.
function highlightSnippet(citation: ResultCitation) {
  const { snippet, char_start, char_end } = citation
  const validSpan =
    Number.isInteger(char_start) &&
    Number.isInteger(char_end) &&
    char_start >= 0 &&
    char_end > char_start &&
    char_end <= snippet.length

  if (!validSpan) {
    return <span>{snippet}</span>
  }

  return (
    <>
      <span>{snippet.slice(0, char_start)}</span>
      <mark className="cite">
        {snippet.slice(char_start, char_end)}
      </mark>
      <span>{snippet.slice(char_end)}</span>
    </>
  )
}

export default function QueryPlanPage() {
  const [question, setQuestion] = useState("")
  const [runId, setRunId] = useState(() =>
    typeof window === "undefined"
      ? ""
      : window.localStorage.getItem("citespan.demo.run_id") || ""
  )
  const [loading, setLoading] = useState<"reset" | "run" | "preview" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sampleStatus, setSampleStatus] = useState<string | null>(() =>
    typeof window === "undefined"
      ? null
      : window.localStorage.getItem("citespan.demo.run_id")
        ? "Sample loaded: canonical synthetic UFDR."
        : null
  )
  const [response, setResponse] = useState<AnyResponse | null>(null)

  const resetToSample = async () => {
    setLoading("reset")
    setError(null)
    setSampleStatus(null)
    setResponse(null)
    try {
      const result = await authedFetch(`${API_BASE_URL}/demo/reset`, { method: "POST" })
      const body = (await result.json()) as {
        run_id?: string
        sample?: string
        detail?: string
      }
      if (!result.ok) {
        throw new Error(body.detail || `Demo reset failed: ${result.status}`)
      }
      if (!body.run_id || body.sample !== "canonical synthetic UFDR") {
        throw new Error("Demo reset did not return the canonical synthetic run.")
      }
      window.localStorage.setItem("citespan.demo.run_id", body.run_id)
      setRunId(body.run_id)
      setSampleStatus("Sample loaded: canonical synthetic UFDR.")
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(null)
    }
  }

  const submit = async (mode: "run" | "preview") => {
    if (!question.trim()) {
      setError("Enter a question first.")
      return
    }
    if (!runId.trim()) {
      setError("Reset to sample before you run a query.")
      return
    }
    setLoading(mode)
    setError(null)
    try {
      const body = { question: question.trim(), run_id: runId.trim() }
      const result =
        mode === "run" ? await runQueryPlan(body) : await previewQueryPlan(body)
      setResponse(result)
    } catch (err) {
      // Do not swallow — surface the backend error text verbatim.
      setError(err instanceof Error ? err.message : String(err))
      setResponse(null)
    } finally {
      setLoading(null)
    }
  }

  const busy = loading !== null

  return (
    <div className="min-h-screen bg-background">
      <header className="w-full border-b bg-background/80 px-4 py-5 backdrop-blur-md sm:px-8">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Seal size={28} />
            <span className="text-xl font-medium text-foreground">CiteSpan</span>
          </Link>
          <Badge variant="signal">Auditable Query</Badge>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-foreground">
            Natural language to cited evidence
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Ask a question in plain English. Every answer is traceable: the
            structured query plan, the compiled SQL, and the exact rows and
            character spans each result was matched on.
          </p>
        </div>

        {/* Query form */}
        <Card className="mb-8">
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <label
                htmlFor="question"
                className="text-sm font-medium text-foreground"
              >
                Question
              </label>
              <Input
                id="question"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy) submit("run")
                }}
                placeholder="e.g. Show me all messages mentioning a bank transfer"
                disabled={busy}
              />
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="run-id" className="text-sm font-medium text-foreground">
                Run ID
              </label>
              <Input
                id="run-id"
                value={runId}
                disabled={busy}
                readOnly
                placeholder="Use Reset to sample to select the demo run"
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground">
                DEMO_MODE uses the canonical synthetic sample. Reset it before a query.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                onClick={resetToSample}
                disabled={busy}
              >
                {loading === "reset" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Database className="h-4 w-4" />
                )}
                Reset to sample
              </Button>
              <Button
                variant="signal"
                onClick={() => submit("run")}
                disabled={busy}
              >
                {loading === "run" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Run query
              </Button>
              <Button
                variant="outline"
                onClick={() => submit("preview")}
                disabled={busy}
              >
                {loading === "preview" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
                Preview plan
              </Button>
            </div>

            {sampleStatus && (
              <p role="status" className="text-sm text-signal">
                {sampleStatus}
              </p>
            )}

            <div className="flex flex-wrap gap-2 pt-1">
              {SAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setQuestion(q)}
                  disabled={busy}
                  className="rounded-full bg-signal/10 border border-signal/25 px-3 py-1 text-xs text-signal transition-colors hover:bg-signal/20 disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Error state */}
        {error && (
          <div className="mb-8 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">Request failed</p>
              <p className="mt-1 whitespace-pre-wrap break-words font-mono text-xs text-red-700">
                {error}
              </p>
            </div>
          </div>
        )}

        {/* Results */}
        {response && (
          <div className="space-y-8">
            {/* (a) Query Plan */}
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="flex items-center gap-2">
                    <ListTree className="h-4 w-4 text-signal" />
                    Query Plan
                  </CardTitle>
                  <Badge
                    variant="secondary"
                  >
                    planner: {response.planner === "stub" ? "deterministic demo planner" : "configured planner"}
                  </Badge>
                </div>
                <CardDescription>
                  The structured intermediate representation derived from the
                  question.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {response.plan.rationale && (
                  <p className="mb-4 rounded-lg bg-signal/10 border border-signal/20 px-3 py-2 text-sm text-foreground">
                    {response.plan.rationale}
                  </p>
                )}
                <pre className="overflow-x-auto rounded-lg bg-[oklch(0.135_0.012_256)] p-4 font-mono text-xs leading-relaxed text-foreground">
                  {JSON.stringify(response.plan, null, 2)}
                </pre>
              </CardContent>
            </Card>

            {/* (b) Compiled SQL */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-signal" />
                  Compiled SQL
                </CardTitle>
                <CardDescription>
                  The exact query rendered from the plan and executed against the
                  evidence store.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <pre className="overflow-x-auto rounded-lg bg-[oklch(0.135_0.012_256)] p-4 font-mono text-xs leading-relaxed text-signal">
                  {response.sql}
                </pre>
              </CardContent>
            </Card>

            {/* (c) Cited Results — only present on a full run */}
            {isFullRun(response) ? (
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-signal" />
                      Cited Results
                    </CardTitle>
                    <Badge variant="outline">
                      {response.total} match{response.total === 1 ? "" : "es"}
                    </Badge>
                  </div>
                  <CardDescription>
                    Each row links back to its source table, row, and the exact
                    text span that matched.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {response.rows.length === 0 ? (
                    <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                      No rows matched this query.
                    </p>
                  ) : (
                    response.rows.map((row) => (
                      <div
                        key={`${row.source_table}:${row.row_id}`}
                        data-testid="cited-result-row"
                        className="rounded-xl border bg-card p-4"
                      >
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <Badge
                            variant="signal"
                            className="font-mono"
                          >
                            {row.source_table}
                          </Badge>
                          <span className="font-mono text-muted-foreground">
                            #{row.row_id}
                          </span>
                          {row.event_time && (
                            <span className="ml-auto text-muted-foreground">
                              {row.event_time}
                            </span>
                          )}
                        </div>

                        <p className="mt-2 text-sm text-foreground">
                          {row.preview}
                        </p>

                        {row.citations.length > 0 && (
                          <div className="mt-3 space-y-2 border-t pt-3">
                            {row.citations.map((c, i) => (
                              <div
                                key={`${c.column}:${c.char_start}:${i}`}
                                className="rounded-lg bg-surface-1 p-3 text-xs"
                              >
                                <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
                                  <Quote className="h-3 w-3 text-signal" />
                                  <span className="font-mono font-medium text-foreground">
                                    {c.column}
                                  </span>
                                  <span aria-hidden>•</span>
                                  <span className="font-mono text-signal">
                                    {c.matched_value}
                                  </span>
                                  <span aria-hidden>•</span>
                                  <span className="font-mono">
                                    chars {c.char_start}–{c.char_end}
                                  </span>
                                </div>
                                <p className="mt-2 leading-relaxed text-foreground">
                                  {highlightSnippet(c)}
                                </p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>
            ) : (
              <div className="rounded-xl border border-dashed border-signal/40 bg-signal/5 px-4 py-6 text-center text-sm text-signal">
                Preview only — the query was not executed.{" "}
                <button
                  type="button"
                  onClick={() => submit("run")}
                  disabled={busy}
                  className="font-medium underline underline-offset-2 disabled:opacity-50"
                >
                  Run it
                </button>{" "}
                to see cited results.
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
