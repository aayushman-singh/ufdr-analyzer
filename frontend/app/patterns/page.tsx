"use client"

import { useState } from "react"
import Link from "next/link"
import {
  Activity,
  Loader2,
  AlertTriangle,
  TrendingUp,
  Calendar,
} from "lucide-react"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts"

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
import {
  getPatterns,
  type PatternsResponse,
  type Finding,
  type Severity,
} from "@/lib/analyticsApi"

function FindingCard({ finding }: { finding: Finding }) {
  const variantMap: Record<Severity, "high" | "medium" | "low"> = {
    high: "high",
    medium: "medium",
    low: "low",
  }

  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={variantMap[finding.severity]}>{finding.severity}</Badge>
        <span className="font-mono text-xs text-muted-foreground">{finding.type}</span>
        <Badge variant="signal" className="ml-auto">
          {finding.citations.length} citation
          {finding.citations.length === 1 ? "" : "s"}
        </Badge>
      </div>

      <h3 className="mt-2 text-sm font-semibold text-foreground">
        {finding.title}
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">{finding.description}</p>

      {finding.dates.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
          <Calendar className="h-3 w-3 text-muted-foreground" />
          {finding.dates.map((d) => (
            <span
              key={d}
              className="rounded bg-surface-1 px-1.5 py-0.5 font-mono text-xs text-muted-foreground"
            >
              {d}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function PatternsPage() {
  const [runId, setRunId] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [response, setResponse] = useState<PatternsResponse | null>(null)

  const submit = async () => {
    if (!runId.trim()) {
      setError("Enter a Run ID first.")
      return
    }
    setLoading(true)
    setError(null)
    try {
      const result = await getPatterns(runId.trim())
      setResponse(result)
    } catch (err) {
      // Do not swallow — surface the backend error text verbatim.
      setError(err instanceof Error ? err.message : String(err))
      setResponse(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="w-full border-b bg-background/80 px-4 py-5 backdrop-blur-md sm:px-8">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Seal size={28} />
            <span className="text-xl font-medium text-foreground">CiteSpan</span>
          </Link>
          <Badge variant="signal">Behavioural Patterns</Badge>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-foreground">
            Behavioural pattern detection
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Surface anomalies across a device&apos;s communication timeline —
            activity spikes, late-night bursts, sudden drops and new contacts —
            each backed by citations to the underlying evidence.
          </p>
        </div>

        {/* Form */}
        <Card className="mb-8">
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="run-id" className="text-sm font-medium text-foreground">
                Run ID
              </label>
              <Input
                id="run-id"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !loading) submit()
                }}
                placeholder="Extraction run UUID"
                disabled={loading}
                className="font-mono"
              />
            </div>
            <div>
              <Button
                variant="signal"
                onClick={submit}
                disabled={loading}
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Activity className="h-4 w-4" />
                )}
                Analyze
              </Button>
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
        {response && (() => {
          // Collect spike dates from findings of type "spike" to highlight in chart.
          const spikeDates = new Set<string>(
            response.findings
              .filter((f) => f.type === "spike")
              .flatMap((f) => f.dates),
          )

          return (
            <div className="space-y-8">
              {/* Narrative hero */}
              <div className="rounded-2xl border border-signal/30 bg-signal/10 p-6">
                <div className="flex items-center gap-2 text-signal">
                  <TrendingUp className="h-5 w-5" />
                  <span className="text-sm font-semibold uppercase tracking-wide">
                    Narrative
                  </span>
                </div>
                <p className="mt-2 text-base leading-relaxed text-foreground">
                  {response.narrative}
                </p>
                <div className="mt-4 flex flex-wrap gap-3 text-xs text-muted-foreground">
                  <span className="rounded-full bg-background/50 px-3 py-1">
                    {response.total_events.toLocaleString()} events
                  </span>
                  <span className="rounded-full bg-background/50 px-3 py-1">
                    {response.span_start} → {response.span_end}
                  </span>
                  <span className="rounded-full bg-background/50 px-3 py-1">
                    {response.findings.length} finding
                    {response.findings.length === 1 ? "" : "s"}
                  </span>
                </div>
              </div>

              {/* Daily activity chart */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Activity className="h-4 w-4 text-signal" />
                    Daily activity
                  </CardTitle>
                  <CardDescription>
                    Total events (messages + calls) per day across the timeline.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {response.daily_series.length === 0 ? (
                    <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                      No daily activity recorded for this run.
                    </p>
                  ) : (
                    <div className="h-72 w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart
                          data={response.daily_series}
                          margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
                        >
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="var(--border)"
                            vertical={false}
                          />
                          <XAxis
                            dataKey="date"
                            tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                            tickLine={false}
                            axisLine={{ stroke: "var(--border)" }}
                            minTickGap={24}
                          />
                          <YAxis
                            tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                            tickLine={false}
                            axisLine={false}
                            allowDecimals={false}
                          />
                          <Tooltip
                            cursor={{ fill: "var(--surface-3)" }}
                            contentStyle={{
                              background: "var(--popover)",
                              border: "1px solid var(--border)",
                              borderRadius: 12,
                              color: "var(--foreground)",
                              fontSize: 12,
                            }}
                          />
                          <Bar
                            dataKey="total"
                            fill="var(--chart-1)"
                            radius={[4, 4, 0, 0]}
                            name="Total events"
                          >
                            {response.daily_series.map((point) => (
                              <Cell
                                key={point.date}
                                fill={
                                  spikeDates.has(point.date)
                                    ? "var(--signal)"
                                    : "var(--chart-1)"
                                }
                              />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Findings */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-signal" />
                    Findings
                  </CardTitle>
                  <CardDescription>
                    Detected anomalies, ordered as returned by CiteSpan.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {response.findings.length === 0 ? (
                    <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                      No anomalies detected for this run.
                    </p>
                  ) : (
                    response.findings.map((f, i) => (
                      <FindingCard key={`${f.type}:${i}`} finding={f} />
                    ))
                  )}
                </CardContent>
              </Card>
            </div>
          )
        })()}
      </main>
    </div>
  )
}
