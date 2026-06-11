import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Clock, Calendar } from "lucide-react"
import { mockTimelineData } from "../data"

export function TimelineAnalysisView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-foreground tracking-tight mb-2">Timeline Analysis</h2>
        <p className="text-lg text-muted-foreground font-light">Chronological visualization of events and activities</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-3">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-foreground font-medium">
                <Clock className="w-5 h-5 text-signal" />
                Interactive Timeline - March 15-16, 2024
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-6">
                {mockTimelineData.map((item, index) => (
                  <div key={index} className="flex items-start gap-4">
                    <div className="flex flex-col items-center">
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center ${ item.type === "location" ? "bg-info/15 text-info" : item.type === "message" ? "bg-[var(--severity-low)]/15 text-[var(--severity-low)]" : item.type === "call" ? "bg-signal/15 text-signal" : item.type === "deleted" ? "bg-destructive/15 text-destructive" : "bg-[var(--severity-medium)]/15 text-[var(--severity-medium)]" }`}>
                        <item.icon className="w-5 h-5" />
                      </div>
                      {index < mockTimelineData.length - 1 && <div className="w-px h-8 bg-border mt-2" />}
                    </div>
                    <div className="flex-1 pb-8">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-medium text-foreground">{item.time}</span>
                        <Badge variant="outline" className="text-xs">{item.date}</Badge>
                        {item.type === "deleted" && <Badge variant="destructive" className="text-xs">Deleted</Badge>}
                      </div>
                      <p className="text-muted-foreground">{item.event}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-medium text-foreground">Timeline Controls</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Button className="w-full bg-primary hover:bg-primary/80">
                <Calendar className="w-4 h-4 mr-2" /> Select Date Range
              </Button>
              <div className="space-y-2">
                <label className="text-sm font-medium text-muted-foreground">Event Types</label>
                {["Messages", "Calls", "Locations", "Financial", "Deleted"].map((type) => (
                  <label key={type} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" className="rounded" defaultChecked /> {type}
                  </label>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
