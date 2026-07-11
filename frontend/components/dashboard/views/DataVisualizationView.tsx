"use client"

import { useEffect, useState } from "react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  ChartContainer,
  ChartConfig,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
} from "@/components/ui/chart"
import { BarChart, Bar, CartesianGrid, XAxis, YAxis } from "recharts"
import {
  Network,
  BarChart3,
  MapPin,
  TrendingUp,
  ArrowLeft,
  Loader2,
  AlertTriangle,
} from "lucide-react"
import { getPatterns, type PatternsResponse } from "@/lib/analyticsApi"

type ChartRow = {
  date: string
  calls: number
  messages: number
  total: number
}

function toChartRows(patterns: PatternsResponse | null): ChartRow[] {
  return (patterns?.daily_series ?? []).map((point) => ({
    date: point.date,
    calls: point.calls,
    messages: point.messages,
    total: point.total,
  }))
}

const chartConfig = {
  calls: {
    label: "Calls",
    color: "hsl(var(--chart-1))",
  },
  messages: {
    label: "Messages",
    color: "hsl(var(--chart-2))",
  },
} satisfies ChartConfig

export function DataVisualizationView() {
  const [activeView, setActiveView] = useState<"grid" | "chart">("grid")
  const [patterns, setPatterns] = useState<PatternsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)

      const runId = window.localStorage.getItem("run_id")
      if (!runId) {
        if (!cancelled) {
          setPatterns(null)
          setError(
            "No active analysis session found. Upload or reset a case first.",
          )
          setLoading(false)
        }
        return
      }

      try {
        const result = await getPatterns(runId)
        if (!cancelled) {
          setPatterns(result)
        }
      } catch (err) {
        if (!cancelled) {
          setPatterns(null)
          setError(err instanceof Error ? err.message : String(err))
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [reloadToken])

  const chartData = toChartRows(patterns)
  const retry = () => setReloadToken((token) => token + 1)

  if (loading) {
    return (
      <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 rounded-lg border border-border bg-surface-1 p-8 text-center">
        <Loader2 className="h-8 w-8 animate-spin text-signal" />
        <p className="text-sm text-muted-foreground">
          Loading communication activity...
        </p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex min-h-[320px] flex-col items-center justify-center gap-4 rounded-lg border border-red-200 bg-red-50 p-8 text-center">
        <AlertTriangle className="h-8 w-8 text-red-700" />
        <div className="max-w-lg space-y-1">
          <p className="font-medium text-red-800">Unable to load analytics</p>
          <p className="whitespace-pre-wrap break-words font-mono text-xs text-red-700">
            {error}
          </p>
        </div>
        <Button variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    )
  }

  if (chartData.length === 0) {
    return (
      <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 rounded-lg border border-border bg-surface-1 p-8 text-center">
        <BarChart3 className="h-10 w-10 text-muted-foreground" />
        <div className="space-y-1">
          <p className="font-medium text-foreground">No activity data</p>
          <p className="text-sm text-muted-foreground">
            This run has no daily communication series to chart yet.
          </p>
        </div>
        <Button variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    )
  }

  const peakDay = chartData.reduce((best, row) =>
    row.total > best.total ? row : best,
  )
  const activitySummary = `Peak: ${peakDay.date} (${peakDay.total.toLocaleString()}) | ${patterns!.total_events.toLocaleString()} total events | ${patterns!.findings.length} findings`

  // Grid view of all cards
  const GridView = () => (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-foreground tracking-tight mb-2">
          Data Visualization
        </h2>
        <p className="text-lg text-muted-foreground font-light">
          Interactive charts and network diagrams
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Card 1 */}
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground font-medium">
              <Network className="w-5 h-5 text-signal" /> Contact Network
            </CardTitle>
            <CardDescription>Relationship mapping between entities</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-surface-1 border border-border rounded-lg p-8 text-center h-64 flex flex-col justify-center">
              <Network className="w-16 h-16 mx-auto mb-4 text-signal" />
              <p className="text-muted-foreground font-medium mb-2">
                Interactive Network Diagram
              </p>
              <p className="text-sm text-muted-foreground mb-4">
                Available in Graph Analysis
              </p>
              <Button className="bg-primary hover:bg-primary/80" disabled>
                Launch Interactive View
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Card 2 */}
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground font-medium">
              <BarChart3 className="w-5 h-5 text-info" /> Communication Timeline
            </CardTitle>
            <CardDescription>Message and call frequency over time</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-surface-1 border border-border rounded-lg p-8 text-center h-64 flex flex-col justify-center">
              <BarChart3 className="w-16 h-16 mx-auto mb-4 text-info" />
              <p className="text-muted-foreground font-medium mb-2">Activity Chart</p>
              <p className="text-sm text-muted-foreground mb-4">{activitySummary}</p>
              <Button variant="outline" onClick={() => setActiveView("chart")}>
                View Chart
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Card 3 */}
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground font-medium">
              <MapPin className="w-5 h-5 text-[var(--severity-low)]" /> Location Heatmap
            </CardTitle>
            <CardDescription>Geographic movement patterns</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-surface-1 border border-border rounded-lg p-8 text-center h-64 flex flex-col justify-center">
              <MapPin className="w-16 h-16 mx-auto mb-4 text-[var(--severity-low)]" />
              <p className="text-muted-foreground font-medium mb-2">Movement Heatmap</p>
              <p className="text-sm text-muted-foreground mb-4">
                No location analytics endpoint is wired here
              </p>
              <Button variant="outline" disabled>View Map</Button>
            </div>
          </CardContent>
        </Card>

        {/* Card 4 */}
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground font-medium">
              <TrendingUp className="w-5 h-5 text-[var(--severity-medium)]" /> Risk Assessment
            </CardTitle>
            <CardDescription>AI-powered risk scoring visualization</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-surface-1 border border-border rounded-lg p-8 text-center h-64 flex flex-col justify-center">
              <TrendingUp className="w-16 h-16 mx-auto mb-4 text-[var(--severity-medium)]" />
              <p className="text-muted-foreground font-medium mb-2">Risk Dashboard</p>
              <p className="text-sm text-muted-foreground mb-4">
                Risk scoring is not connected to this analytics response
              </p>
              <Button variant="outline" disabled>View Dashboard</Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )

  // Chart view for communication timeline
  const ChartView = () => (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="outline" size="icon" onClick={() => setActiveView("grid")}>
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <div>
          <h2 className="text-4xl font-light text-foreground tracking-tight">
            Communication Timeline
          </h2>
          <p className="text-lg text-muted-foreground font-light">
            Daily calls and messages for this extraction run.
          </p>
        </div>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Communication Activity</CardTitle>
          <CardDescription>
            {patterns!.span_start} to {patterns!.span_end} | {activitySummary}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ChartContainer config={chartConfig} className="min-h-[400px] w-full">
            <BarChart accessibilityLayer data={chartData}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="date"
                tickLine={false}
                tickMargin={10}
                axisLine={false}
              />
              <YAxis />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar
                dataKey="calls"
                stackId="a"
                fill="var(--color-calls)"
                radius={[4, 4, 0, 0]}
              />
              <Bar
                dataKey="messages"
                stackId="a"
                fill="var(--color-messages)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ChartContainer>
        </CardContent>
      </Card>
    </div>
  )

  return activeView === "grid" ? <GridView /> : <ChartView />
}
