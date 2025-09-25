"use client"

import { useState } from "react"
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
} from "lucide-react"

// Mock data for the bar chart
const mockChartData = [
  { date: "Sep 18", calls: 8, messages: 22, media: 5 },
  { date: "Sep 19", calls: 12, messages: 35, media: 8 },
  { date: "Sep 20", calls: 5, messages: 15, media: 12 },
  { date: "Sep 21", calls: 18, messages: 45, media: 7 },
  { date: "Sep 22", calls: 25, messages: 60, media: 15 },
  { date: "Sep 23", calls: 10, messages: 30, media: 10 },
  { date: "Sep 24", calls: 14, messages: 28, media: 9 },
]

// Chart configuration for colors + labels
const chartConfig = {
  calls: {
    label: "Calls",
    color: "hsl(var(--chart-1))",
  },
  messages: {
    label: "Messages",
    color: "hsl(var(--chart-2))",
  },
  media: {
    label: "Media Files",
    color: "hsl(var(--chart-3))",
  },
} satisfies ChartConfig

export function DataVisualizationView() {
  const [activeView, setActiveView] = useState<"grid" | "chart">("grid")

  // Grid view of all cards
  const GridView = () => (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-slate-900 tracking-tight mb-2">
          Data Visualization
        </h2>
        <p className="text-lg text-slate-600 font-light">
          Interactive charts and network diagrams
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Card 1 */}
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
              <Network className="w-5 h-5 text-purple-600" /> Contact Network
            </CardTitle>
            <CardDescription>Relationship mapping between entities</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-lg p-8 text-center h-64 flex flex-col justify-center">
              <Network className="w-16 h-16 mx-auto mb-4 text-purple-600" />
              <p className="text-slate-700 font-medium mb-2">
                Interactive Network Diagram
              </p>
              <p className="text-sm text-slate-600 mb-4">
                89 contacts • 234 connections
              </p>
              <Button className="bg-slate-900 hover:bg-slate-700">
                Launch Interactive View
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Card 2 */}
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
              <BarChart3 className="w-5 h-5 text-blue-600" /> Communication Timeline
            </CardTitle>
            <CardDescription>Message and call frequency over time</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-8 text-center h-64 flex flex-col justify-center">
              <BarChart3 className="w-16 h-16 mx-auto mb-4 text-blue-600" />
              <p className="text-slate-700 font-medium mb-2">Activity Chart</p>
              <p className="text-sm text-slate-600 mb-4">
                Peak: 2-4 PM • 2,847 total events
              </p>
              <Button variant="outline" onClick={() => setActiveView("chart")}>
                View Chart
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Card 3 */}
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
              <MapPin className="w-5 h-5 text-green-600" /> Location Heatmap
            </CardTitle>
            <CardDescription>Geographic movement patterns</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-8 text-center h-64 flex flex-col justify-center">
              <MapPin className="w-16 h-16 mx-auto mb-4 text-green-600" />
              <p className="text-slate-700 font-medium mb-2">Movement Heatmap</p>
              <p className="text-sm text-slate-600 mb-4">
                47 locations • 234 miles traveled
              </p>
              <Button variant="outline">View Map</Button>
            </div>
          </CardContent>
        </Card>

        {/* Card 4 */}
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
              <TrendingUp className="w-5 h-5 text-orange-600" /> Risk Assessment
            </CardTitle>
            <CardDescription>AI-powered risk scoring visualization</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-gradient-to-br from-orange-50 to-orange-100 rounded-lg p-8 text-center h-64 flex flex-col justify-center">
              <TrendingUp className="w-16 h-16 mx-auto mb-4 text-orange-600" />
              <p className="text-slate-700 font-medium mb-2">Risk Dashboard</p>
              <p className="text-sm text-slate-600 mb-4">
                Score: 8.7/10 • 15 anomalies detected
              </p>
              <Button variant="outline">View Dashboard</Button>
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
          <h2 className="text-4xl font-light text-slate-900 tracking-tight">
            Communication Timeline
          </h2>
          <p className="text-lg text-slate-600 font-light">
            Analysis of messages, calls, and media files exchanged over the past week.
          </p>
        </div>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Communication Activity - Last 7 Days</CardTitle>
          <CardDescription>Daily breakdown of communications by type.</CardDescription>
        </CardHeader>
        <CardContent>
          <ChartContainer config={chartConfig} className="min-h-[400px] w-full">
            <BarChart accessibilityLayer data={mockChartData}>
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
              <Bar
                dataKey="media"
                stackId="a"
                fill="var(--color-media)"
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
