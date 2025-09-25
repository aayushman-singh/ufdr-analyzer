import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { FileText, TrendingUp, Users, MapPin, Zap, Activity, Download, Eye, Network } from "lucide-react"

export function ReportsAnalyticsView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-slate-900 tracking-tight mb-2">Reports & Analytics</h2>
        <p className="text-lg text-slate-600 font-light">Generate comprehensive reports and visualizations</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
              <FileText className="w-5 h-5 text-purple-600" /> Investigation Report
            </CardTitle>
            <CardDescription>Comprehensive case analysis</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 mb-4">
              <div className="flex justify-between text-sm"><span className="text-slate-600">Evidence Items</span><span className="font-medium">2,847</span></div>
              <div className="flex justify-between text-sm"><span className="text-slate-600">Key Findings</span><span className="font-medium">23</span></div>
              <div className="flex justify-between text-sm"><span className="text-slate-600">Suspects</span><span className="font-medium">3</span></div>
            </div>
            <Button className="w-full bg-slate-900 hover:bg-slate-700"><Download className="w-4 h-4 mr-2" /> Generate PDF</Button>
          </CardContent>
        </Card>

        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
              <TrendingUp className="w-5 h-5 text-blue-600" /> Communication Analysis
            </CardTitle>
            <CardDescription>Message and call patterns</CardDescription>
          </CardHeader>
          <CardContent>
             <div className="space-y-3 mb-4">
               <div className="flex justify-between text-sm"><span className="text-slate-600">Peak Activity</span><span className="font-medium">2-4 PM</span></div>
               <div className="flex justify-between text-sm"><span className="text-slate-600">Most Contacted</span><span className="font-medium">Mike Johnson</span></div>
               <div className="flex justify-between text-sm"><span className="text-slate-600">Deleted Messages</span><span className="font-medium text-red-600">156</span></div>
             </div>
            <Button variant="outline" className="w-full bg-transparent"><Eye className="w-4 h-4 mr-2" /> View Details</Button>
          </CardContent>
        </Card>

        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
              <Users className="w-5 h-5 text-green-600" /> Network Analysis
            </CardTitle>
            <CardDescription>Contact relationships</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 mb-4">
              <div className="flex justify-between text-sm"><span className="text-slate-600">Total Contacts</span><span className="font-medium">89</span></div>
              <div className="flex justify-between text-sm"><span className="text-slate-600">Suspicious Links</span><span className="font-medium text-orange-600">12</span></div>
              <div className="flex justify-between text-sm"><span className="text-slate-600">Network Depth</span><span className="font-medium">4 levels</span></div>
            </div>
            <Button variant="outline" className="w-full bg-transparent"><Network className="w-4 h-4 mr-2" /> View Network</Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}