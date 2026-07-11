"use client"

import { useMemo, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Search, Filter, Loader2, AlertTriangle } from "lucide-react"
import {
  runQueryPlan,
  type QueryPlanResponse,
} from "@/lib/queryPlanApi"

const CONTENT_SCOPES = [
  "Messages",
  "Calls",
  "Media",
  "Locations",
  "Contacts",
  "Deleted",
] as const

type ContentScope = (typeof CONTENT_SCOPES)[number]

const DEFAULT_SCOPES: ContentScope[] = [
  "Messages",
  "Calls",
  "Media",
  "Locations",
  "Contacts",
]

function buildSearchQuestion(
  query: string,
  scopes: ContentScope[],
  startDate: string,
  endDate: string,
): string {
  const parts: string[] = [query.trim()]

  if (scopes.length > 0) {
    parts.push(`Focus on these content types: ${scopes.join(", ")}.`)
  }

  if (startDate && endDate) {
    parts.push(`Limit results to the date range from ${startDate} to ${endDate}.`)
  } else if (startDate) {
    parts.push(`Limit results to events on or after ${startDate}.`)
  } else if (endDate) {
    parts.push(`Limit results to events on or before ${endDate}.`)
  }

  return parts.join(" ")
}

function formatEventTime(eventTime: string | null): string {
  if (!eventTime) return "Unknown time"
  const parsed = new Date(eventTime)
  if (Number.isNaN(parsed.getTime())) return eventTime
  return parsed.toLocaleString()
}

export function EvidenceSearchView() {
  const [query, setQuery] = useState("")
  const [selectedScopes, setSelectedScopes] = useState<ContentScope[]>(DEFAULT_SCOPES)
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [response, setResponse] = useState<QueryPlanResponse | null>(null)
  const [hasSubmitted, setHasSubmitted] = useState(false)

  const shapedQuestion = useMemo(
    () => buildSearchQuestion(query, selectedScopes, startDate, endDate),
    [query, selectedScopes, startDate, endDate],
  )

  const toggleScope = (scope: ContentScope) => {
    setSelectedScopes((current) =>
      current.includes(scope)
        ? current.filter((item) => item !== scope)
        : [...current, scope],
    )
  }

  const submit = async () => {
    setHasSubmitted(true)

    if (!query.trim()) {
      setError("Enter a search query first.")
      setResponse(null)
      return
    }

    if (startDate && endDate && startDate > endDate) {
      setError("Start date must be on or before end date.")
      setResponse(null)
      return
    }

    const runId =
      typeof window !== "undefined" ? window.localStorage.getItem("run_id") : null

    if (!runId) {
      setError(
        "No active analysis run found. Upload or open a case so a run_id is available.",
      )
      setResponse(null)
      return
    }

    setLoading(true)
    setError(null)

    try {
      const result = await runQueryPlan({
        question: shapedQuestion,
        run_id: runId,
        context: {
          content_types: selectedScopes,
          start_date: startDate || null,
          end_date: endDate || null,
        },
      })
      setResponse(result)
    } catch (err) {
      setResponse(null)
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const resultsDescription = (() => {
    if (loading) return "Searching the active run..."
    if (error) return "Search could not be completed"
    if (!hasSubmitted) return "Submit a query to search the active run"
    if (response) {
      return response.total === 0
        ? "No matching evidence rows"
        : `Found ${response.total} item${response.total === 1 ? "" : "s"} matching your criteria`
    }
    return "Submit a query to search the active run"
  })()

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-foreground tracking-tight mb-2">
          Evidence Search
        </h2>
        <p className="text-lg text-muted-foreground font-light">
          Advanced search capabilities across all forensic data
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-foreground font-medium">
                <Search className="w-5 h-5 text-signal" />
                Smart Search
              </CardTitle>
            </CardHeader>
            <CardContent>
              <form
                className="flex gap-2 mb-4"
                onSubmit={(event) => {
                  event.preventDefault()
                  void submit()
                }}
              >
                <Input
                  placeholder="Search messages, calls, locations..."
                  className="flex-1"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  disabled={loading}
                />
                <Button
                  type="submit"
                  className="bg-primary hover:bg-primary/80"
                  disabled={loading}
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Search className="w-4 h-4" />
                  )}
                </Button>
              </form>
              <div className="flex gap-2 flex-wrap">
                {CONTENT_SCOPES.map((tag) => {
                  const active = selectedScopes.includes(tag)
                  return (
                    <Badge
                      key={tag}
                      variant={active ? "default" : "outline"}
                      className="cursor-pointer hover:bg-surface-3"
                      onClick={() => toggleScope(tag)}
                    >
                      {tag}
                    </Badge>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-medium text-foreground">
                Search Results
              </CardTitle>
              <CardDescription>{resultsDescription}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {loading && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Running auditable query plan...
                </div>
              )}

              {!loading && error && (
                <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <p>{error}</p>
                </div>
              )}

              {!loading && !error && hasSubmitted && response && response.total === 0 && (
                <p className="text-sm text-muted-foreground">
                  No evidence rows matched this query for the active run.
                </p>
              )}

              {!loading &&
                !error &&
                response &&
                response.rows.map((row) => (
                  <div
                    key={`${row.source_table}:${row.row_id}`}
                    className="space-y-2 rounded-lg border p-3 transition-colors hover:bg-surface-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className="text-xs">
                            {row.source_table}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {formatEventTime(row.event_time)}
                          </span>
                        </div>
                        <p className="text-sm text-foreground">{row.preview}</p>
                      </div>
                    </div>
                    {row.citations.length > 0 && (
                      <div className="space-y-1 border-t pt-2">
                        <p className="text-xs font-medium text-muted-foreground">
                          Citations
                        </p>
                        {row.citations.map((citation, index) => (
                          <p
                            key={`${citation.row_id}:${citation.column}:${index}`}
                            className="text-xs text-muted-foreground"
                          >
                            <span className="font-medium text-foreground">
                              {citation.column}
                            </span>
                            {": "}
                            {citation.snippet || citation.matched_value}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                ))}

              {!loading && !error && !hasSubmitted && (
                <p className="text-sm text-muted-foreground">
                  Results from the query plan will appear here.
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-foreground font-medium">
                <Filter className="w-5 h-5 text-signal" />
                Filters
              </CardTitle>
              <CardDescription>
                These controls shape the question sent to the query planner.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium text-muted-foreground mb-2 block">
                  Date Range
                </label>
                <div className="space-y-2">
                  <Input
                    type="date"
                    className="text-sm"
                    value={startDate}
                    onChange={(event) => setStartDate(event.target.value)}
                    disabled={loading}
                  />
                  <Input
                    type="date"
                    className="text-sm"
                    value={endDate}
                    onChange={(event) => setEndDate(event.target.value)}
                    disabled={loading}
                  />
                </div>
              </div>
              <div>
                <label className="text-sm font-medium text-muted-foreground mb-2 block">
                  Content Type
                </label>
                <div className="space-y-2">
                  {(["Messages", "Calls", "Media", "Locations", "Contacts"] as const).map(
                    (type) => (
                      <label key={type} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="rounded"
                          checked={selectedScopes.includes(type)}
                          onChange={() => toggleScope(type)}
                          disabled={loading}
                        />{" "}
                        {type}
                      </label>
                    ),
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
