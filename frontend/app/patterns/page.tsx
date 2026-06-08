"use client"

import { useState } from "react"
import Link from "next/link"
import {
  Shield,
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
import {
  getPatterns,
  type PatternsResponse,
  type Finding,
  type Severity,
} from "@/lib/analyticsApi"

// Severity -> badge palette (high=red, medium=amber, low=slate).
const SEVERITY_STYLES: Record<Severity, string> = {
  high: "bg-red-100 text-red-700 border-red-200",
  medium: "bg-amber-100 text-amber-700 border-amber-200",
  low: "bg-slate-100 text-slate-600 border-slate-200",
}

function FindingCard({ finding }: { finding: Finding }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className={SEVERITY_STYLES[finding.severity]}>
          {finding.severity}
        </Badge>
        <span className="font-mono text-xs text-slate-400">{finding.type}</span>
        <Badge
          variant="secondary"
          className="ml-auto bg-purple-100 text-purple-700"
        >
          {finding.citations.length} citation
          {finding.citations.length === 1 ? "" : "s"}
        </Badge>
      </div>

      <h3 className="mt-2 text-sm font-semibold text-slate-900">
        {finding.title}
      </h3>
      <p className="mt-1 text-sm text-slate-600">{finding.description}</p>

      {finding.dates.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-3">
          <Calendar className="h-3 w-3 text-slate-400" />
          {finding.dates.map((d) => (
            <span
              key={d}
              className="rounded bg-slate-50 px-1.5 py-0.5 font-mono text-xs text-slate-600"
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
            Behavioural Patterns
          </Badge>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-slate-900">
            Behavioural pattern detection
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">
            Surface anomalies across a device&apos;s communication timeline —
            activity spikes, late-night bursts, sudden drops and new contacts —
            each backed by citations to the underlying evidence.
          </p>
        </div>

        {/* Form */}
        <Card className="mb-8">
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="run-id" className="text-sm font-medium text-slate-800">
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
                className="font-mono focus-visible:ring-purple-500"
              />
            </div>
            <div>
              <Button
                onClick={submit}
                disabled={loading}
                className="bg-slate-900 hover:bg-slate-700"
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
        {response && (
          <div className="space-y-8">
            {/* Narrative hero */}
            <div className="rounded-2xl border border-purple-200 bg-gradient-to-br from-purple-100 to-purple-50 p-6">
              <div className="flex items-center gap-2 text-purple-700">
                <TrendingUp className="h-5 w-5" />
                <span className="text-sm font-semibold uppercase tracking-wide">
                  Narrative
                </span>
              </div>
              <p className="mt-2 text-base leading-relaxed text-slate-800">
                {response.narrative}
              </p>
              <div className="mt-4 flex flex-wrap gap-3 text-xs text-slate-600">
                <span className="rounded-full bg-white/70 px-3 py-1">
                  {response.total_events.toLocaleString()} events
                </span>
                <span className="rounded-full bg-white/70 px-3 py-1">
                  {response.span_start} → {response.span_end}
                </span>
                <span className="rounded-full bg-white/70 px-3 py-1">
                  {response.findings.length} finding
                  {response.findings.length === 1 ? "" : "s"}
                </span>
              </div>
            </div>

            {/* Daily activity chart */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-purple-600" />
                  Daily activity
                </CardTitle>
                <CardDescription>
                  Total events (messages + calls) per day across the timeline.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {response.daily_series.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
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
                          stroke="#e2e8f0"
                          vertical={false}
                        />
                        <XAxis
                          dataKey="date"
                          tick={{ fontSize: 11, fill: "#64748b" }}
                          tickLine={false}
                          axisLine={{ stroke: "#e2e8f0" }}
                          minTickGap={24}
                        />
                        <YAxis
                          tick={{ fontSize: 11, fill: "#64748b" }}
                          tickLine={false}
                          axisLine={false}
                          allowDecimals={false}
                        />
                        <Tooltip
                          cursor={{ fill: "#f1f5f9" }}
                          contentStyle={{
                            borderRadius: 12,
                            border: "1px solid #e2e8f0",
                            fontSize: 12,
                          }}
                        />
                        <Bar
                          dataKey="total"
                          fill="#9333ea"
                          radius={[4, 4, 0, 0]}
                          name="Total events"
                        />
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
                  <TrendingUp className="h-4 w-4 text-purple-600" />
                  Findings
                </CardTitle>
                <CardDescription>
                  Detected anomalies, ordered as returned by the analyzer.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {response.findings.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
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
        )}
      </main>
    </div>
  )
}
