import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Search, Filter } from "lucide-react"

// Mock data for search results
const searchResults = [
  { type: "WhatsApp", contact: "Mike Johnson", preview: "Hey, can you meet me at the usual place?", time: "Mar 15, 2:30 PM", status: "deleted" },
  { type: "Call", contact: "Sarah Wilson", preview: "Outgoing call - 5 minutes", time: "Mar 15, 3:45 PM", status: "normal" },
  { type: "SMS", contact: "+1-555-0123", preview: "The package is ready for pickup", time: "Mar 16, 9:15 AM", status: "flagged" },
  { type: "Location", contact: "Device", preview: "Central Bank, 123 Main St", time: "Mar 16, 10:30 AM", status: "normal" },
]

export function EvidenceSearchView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-slate-900 tracking-tight mb-2">Evidence Search</h2>
        <p className="text-lg text-slate-600 font-light">Advanced search capabilities across all forensic data</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
                <Search className="w-5 h-5 text-purple-600" />
                Smart Search
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-2 mb-4">
                <Input placeholder="Search messages, calls, locations..." className="flex-1" />
                <Button className="bg-slate-900 hover:bg-slate-700">
                  <Search className="w-4 h-4" />
                </Button>
              </div>
              <div className="flex gap-2 flex-wrap">
                {["Messages", "Calls", "Locations", "Media", "Deleted"].map(tag => (
                  <Badge key={tag} variant="outline" className="cursor-pointer hover:bg-purple-50">{tag}</Badge>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-medium text-slate-900">Search Results</CardTitle>
              <CardDescription>Found 156 items matching your criteria</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {searchResults.map((item, index) => (
                <div key={index} className="flex items-center justify-between p-3 border rounded-lg hover:bg-purple-50 transition-colors cursor-pointer">
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${ item.status === "deleted" ? "bg-red-500" : item.status === "flagged" ? "bg-orange-500" : "bg-green-500" }`} />
                    <div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="text-xs">{item.type}</Badge>
                        <span className="font-medium text-slate-900">{item.contact}</span>
                      </div>
                      <p className="text-sm text-slate-600 mt-1">{item.preview}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-slate-500">{item.time}</p>
                    {item.status === "deleted" && <Badge variant="destructive" className="text-xs mt-1">Deleted</Badge>}
                    {item.status === "flagged" && <Badge variant="secondary" className="text-xs mt-1">Flagged</Badge>}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
                <Filter className="w-5 h-5 text-purple-600" />
                Filters
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium text-slate-700 mb-2 block">Date Range</label>
                <div className="space-y-2">
                  <Input type="date" className="text-sm" />
                  <Input type="date" className="text-sm" />
                </div>
              </div>
              <div>
                <label className="text-sm font-medium text-slate-700 mb-2 block">Content Type</label>
                <div className="space-y-2">
                  {["Messages", "Calls", "Media", "Locations", "Contacts"].map((type) => (
                    <label key={type} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" className="rounded" defaultChecked /> {type}
                    </label>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}