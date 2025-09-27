import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Clock, Calendar } from "lucide-react"
import { mockTimelineData } from "../data"

export function TimelineAnalysisView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-slate-900 tracking-tight mb-2">Timeline Analysis</h2>
        <p className="text-lg text-slate-600 font-light">Chronological visualization of events and activities</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-3">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
                <Clock className="w-5 h-5 text-purple-600" />
                Interactive Timeline - March 15-16, 2024
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-6">
                {mockTimelineData.map((item, index) => (
                  <div key={index} className="flex items-start gap-4">
                    <div className="flex flex-col items-center">
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center ${ item.type === "location" ? "bg-blue-100 text-blue-600" : item.type === "message" ? "bg-green-100 text-green-600" : item.type === "call" ? "bg-purple-100 text-purple-600" : item.type === "deleted" ? "bg-red-100 text-red-600" : "bg-orange-100 text-orange-600" }`}>
                        <item.icon className="w-5 h-5" />
                      </div>
                      {index < mockTimelineData.length - 1 && <div className="w-px h-8 bg-slate-200 mt-2" />}
                    </div>
                    <div className="flex-1 pb-8">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-medium text-slate-900">{item.time}</span>
                        <Badge variant="outline" className="text-xs">{item.date}</Badge>
                        {item.type === "deleted" && <Badge variant="destructive" className="text-xs">Deleted</Badge>}
                      </div>
                      <p className="text-slate-600">{item.event}</p>
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
              <CardTitle className="text-lg font-medium text-slate-900">Timeline Controls</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Button className="w-full bg-slate-900 hover:bg-slate-700">
                <Calendar className="w-4 h-4 mr-2" /> Select Date Range
              </Button>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">Event Types</label>
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