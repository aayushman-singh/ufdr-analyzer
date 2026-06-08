"use client"

import { useState } from "react"
import Link from "next/link"
import {
  Shield,
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
      <mark className="rounded bg-purple-200 px-0.5 text-purple-900">
        {snippet.slice(char_start, char_end)}
      </mark>
      <span>{snippet.slice(char_end)}</span>
    </>
  )
}

export default function QueryPlanPage() {
  const [question, setQuestion] = useState("")
  const [runId, setRunId] = useState("")
  const [loading, setLoading] = useState<"run" | "preview" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [response, setResponse] = useState<AnyResponse | null>(null)

  const submit = async (mode: "run" | "preview") => {
    if (!question.trim()) {
      setError("Enter a question first.")
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
    <div className="min-h-screen bg-gradient-to-b from-purple-50 to-white">
      <header className="w-full border-b border-slate-200 bg-white/80 px-4 py-5 backdrop-blur-sm sm:px-8">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-purple-600 to-purple-800">
              <Shield className="h-4 w-4 text-white" />
            </div>
            <span className="text-xl font-medium text-slate-900">ForensicAI</span>
          </Link>
          <Badge variant="secondary" className="bg-purple-100 text-purple-700">
            Auditable Query
          </Badge>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-slate-900">
            Natural language to cited evidence
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">
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
                className="text-sm font-medium text-slate-800"
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
                className="focus-visible:ring-purple-500"
              />
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="run-id" className="text-sm font-medium text-slate-800">
                Run ID
              </label>
              <Input
                id="run-id"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                placeholder="Optional — leave blank to query the default run"
                disabled={busy}
                className="font-mono focus-visible:ring-purple-500"
              />
              <p className="text-xs text-slate-500">
                Identifies which extraction run to query. Leave blank if unsure.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                onClick={() => submit("run")}
                disabled={busy}
                className="bg-slate-900 hover:bg-slate-700"
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

            <div className="flex flex-wrap gap-2 pt-1">
              {SAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setQuestion(q)}
                  disabled={busy}
                  className="rounded-full bg-purple-50 px-3 py-1 text-xs text-purple-700 transition-colors hover:bg-purple-100 disabled:opacity-50"
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
                    <ListTree className="h-4 w-4 text-purple-600" />
                    Query Plan
                  </CardTitle>
                  <Badge
                    variant={response.planner === "llm" ? "default" : "secondary"}
                    className={
                      response.planner === "llm"
                        ? "bg-purple-600"
                        : "bg-slate-200 text-slate-700"
                    }
                  >
                    planner: {response.planner}
                  </Badge>
                </div>
                <CardDescription>
                  The structured intermediate representation derived from the
                  question.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {response.plan.rationale && (
                  <p className="mb-4 rounded-lg bg-purple-50 px-3 py-2 text-sm text-slate-700">
                    {response.plan.rationale}
                  </p>
                )}
                <pre className="overflow-x-auto rounded-lg bg-slate-900 p-4 font-mono text-xs leading-relaxed text-slate-100">
                  {JSON.stringify(response.plan, null, 2)}
                </pre>
              </CardContent>
            </Card>

            {/* (b) Compiled SQL */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-purple-600" />
                  Compiled SQL
                </CardTitle>
                <CardDescription>
                  The exact query rendered from the plan and executed against the
                  evidence store.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <pre className="overflow-x-auto rounded-lg bg-slate-900 p-4 font-mono text-xs leading-relaxed text-emerald-200">
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
                      <FileText className="h-4 w-4 text-purple-600" />
                      Cited Results
                    </CardTitle>
                    <Badge variant="outline" className="text-slate-600">
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
                    <p className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
                      No rows matched this query.
                    </p>
                  ) : (
                    response.rows.map((row) => (
                      <div
                        key={`${row.source_table}:${row.row_id}`}
                        className="rounded-xl border border-slate-200 bg-white p-4"
                      >
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <Badge
                            variant="secondary"
                            className="bg-purple-100 font-mono text-purple-700"
                          >
                            {row.source_table}
                          </Badge>
                          <span className="font-mono text-slate-400">
                            #{row.row_id}
                          </span>
                          {row.event_time && (
                            <span className="ml-auto text-slate-500">
                              {row.event_time}
                            </span>
                          )}
                        </div>

                        <p className="mt-2 text-sm text-slate-800">
                          {row.preview}
                        </p>

                        {row.citations.length > 0 && (
                          <div className="mt-3 space-y-2 border-t border-slate-100 pt-3">
                            {row.citations.map((c, i) => (
                              <div
                                key={`${c.column}:${c.char_start}:${i}`}
                                className="rounded-lg bg-slate-50 p-3 text-xs"
                              >
                                <div className="flex flex-wrap items-center gap-2 text-slate-500">
                                  <Quote className="h-3 w-3 text-purple-500" />
                                  <span className="font-mono font-medium text-slate-700">
                                    {c.column}
                                  </span>
                                  <span aria-hidden>•</span>
                                  <span className="font-mono text-purple-700">
                                    {c.matched_value}
                                  </span>
                                  <span aria-hidden>•</span>
                                  <span className="font-mono">
                                    chars {c.char_start}–{c.char_end}
                                  </span>
                                </div>
                                <p className="mt-2 leading-relaxed text-slate-700">
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
              <div className="rounded-xl border border-dashed border-purple-200 bg-purple-50/50 px-4 py-6 text-center text-sm text-slate-600">
                Preview only — the query was not executed.{" "}
                <button
                  type="button"
                  onClick={() => submit("run")}
                  disabled={busy}
                  className="font-medium text-purple-700 underline underline-offset-2 disabled:opacity-50"
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
