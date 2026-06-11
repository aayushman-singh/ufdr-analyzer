import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { FileText, TrendingUp, Users, MapPin, Zap, Activity, Download, Eye, Network } from "lucide-react"

export function ReportsAnalyticsView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-foreground tracking-tight mb-2">Reports & Analytics</h2>
        <p className="text-lg text-muted-foreground font-light">Generate comprehensive reports and visualizations</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground font-medium">
              <FileText className="w-5 h-5 text-signal" /> Investigation Report
            </CardTitle>
            <CardDescription>Comprehensive case analysis</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 mb-4">
              <div className="flex justify-between text-sm"><span className="text-muted-foreground">Evidence Items</span><span className="font-medium">2,847</span></div>
              <div className="flex justify-between text-sm"><span className="text-muted-foreground">Key Findings</span><span className="font-medium">23</span></div>
              <div className="flex justify-between text-sm"><span className="text-muted-foreground">Suspects</span><span className="font-medium">3</span></div>
            </div>
            <Button className="w-full bg-primary hover:bg-primary/80"><Download className="w-4 h-4 mr-2" /> Generate PDF</Button>
          </CardContent>
        </Card>

        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground font-medium">
              <TrendingUp className="w-5 h-5 text-info" /> Communication Analysis
            </CardTitle>
            <CardDescription>Message and call patterns</CardDescription>
          </CardHeader>
          <CardContent>
             <div className="space-y-3 mb-4">
               <div className="flex justify-between text-sm"><span className="text-muted-foreground">Peak Activity</span><span className="font-medium">2-4 PM</span></div>
               <div className="flex justify-between text-sm"><span className="text-muted-foreground">Most Contacted</span><span className="font-medium">Mike Johnson</span></div>
               <div className="flex justify-between text-sm"><span className="text-muted-foreground">Deleted Messages</span><span className="font-medium text-destructive">156</span></div>
             </div>
            <Button variant="outline" className="w-full bg-transparent"><Eye className="w-4 h-4 mr-2" /> View Details</Button>
          </CardContent>
        </Card>

        <Card className="hover:shadow-lg transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground font-medium">
              <Users className="w-5 h-5 text-[var(--severity-low)]" /> Network Analysis
            </CardTitle>
            <CardDescription>Contact relationships</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 mb-4">
              <div className="flex justify-between text-sm"><span className="text-muted-foreground">Total Contacts</span><span className="font-medium">89</span></div>
              <div className="flex justify-between text-sm"><span className="text-muted-foreground">Suspicious Links</span><span className="font-medium text-[var(--severity-medium)]">12</span></div>
              <div className="flex justify-between text-sm"><span className="text-muted-foreground">Network Depth</span><span className="font-medium">4 levels</span></div>
            </div>
            <Button variant="outline" className="w-full bg-transparent"><Network className="w-4 h-4 mr-2" /> View Network</Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
