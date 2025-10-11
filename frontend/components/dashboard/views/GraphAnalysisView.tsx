"use client"

import { useState, useEffect } from "react"
import { GraphVisualization } from "@/components/graph/GraphVisualization"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { 
  Network, 
  Users, 
  MessageSquare, 
  Phone, 
  TrendingUp,
  Search,
  Filter,
  BarChart3,
  PieChart
} from "lucide-react"
import { graphApi, GraphData, graphUtils } from "@/lib/api/graph-api"

export function GraphAnalysisView() {
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [stats, setStats] = useState<any>(null)
  const [centralityData, setCentralityData] = useState<any[]>([])
  const [communityData, setCommunityData] = useState<any[]>([])
  const [activeTab, setActiveTab] = useState<'network' | 'analytics' | 'insights'>('network')

  // Load initial data
  useEffect(() => {
    loadGraphData()
  }, [])

  const loadGraphData = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await graphApi.getFullGraph()
      setGraphData(data)
      
      // Calculate stats
      const nodeStats = graphUtils.getNodeStats(data)
      setStats(nodeStats)
      
      // Load analytics data
      await loadAnalyticsData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph data')
    } finally {
      setLoading(false)
    }
  }

  const loadAnalyticsData = async () => {
    try {
      // Load centrality data for Person nodes
      const centrality = await graphApi.getCentrality('Person')
      setCentralityData(centrality)
      
      // Load community data
      const communities = await graphApi.getCommunities('Person')
      setCommunityData(communities)
    } catch (err) {
      console.error('Failed to load analytics data:', err)
    }
  }

  const getNodeTypeIcon = (nodeType: string) => {
    switch (nodeType.toLowerCase()) {
      case 'person':
        return <Users className="w-4 h-4" />
      case 'message':
        return <MessageSquare className="w-4 h-4" />
      case 'call':
        return <Phone className="w-4 h-4" />
      default:
        return <Network className="w-4 h-4" />
    }
  }

  const getNodeTypeColor = (nodeType: string) => {
    switch (nodeType.toLowerCase()) {
      case 'person':
        return 'bg-blue-100 text-blue-800'
      case 'message':
        return 'bg-green-100 text-green-800'
      case 'call':
        return 'bg-purple-100 text-purple-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-4xl font-light text-slate-900 tracking-tight mb-2">
            Graph Analysis
          </h2>
          <p className="text-lg text-slate-600 font-light">
            Loading network data and analytics...
          </p>
        </div>
        <div className="flex items-center justify-center h-96">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-slate-900 mx-auto mb-4"></div>
            <p className="text-slate-600">Loading graph data...</p>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-4xl font-light text-slate-900 tracking-tight mb-2">
            Graph Analysis
          </h2>
          <p className="text-lg text-slate-600 font-light">
            Failed to load graph data
          </p>
        </div>
        <Card>
          <CardContent className="flex items-center justify-center h-96">
            <div className="text-center">
              <div className="text-red-500 mb-4">Error loading graph</div>
              <p className="text-slate-600 mb-4">{error}</p>
              <Button onClick={loadGraphData} variant="outline">
                Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-slate-900 tracking-tight mb-2">
          Graph Analysis
        </h2>
        <p className="text-lg text-slate-600 font-light">
          Network visualization and relationship analysis
        </p>
      </div>

      {/* Tab navigation */}
      <div className="flex space-x-1 bg-slate-100 p-1 rounded-lg w-fit">
        <Button
          variant={activeTab === 'network' ? 'default' : 'ghost'}
          size="sm"
          onClick={() => setActiveTab('network')}
          className="flex items-center gap-2"
        >
          <Network className="w-4 h-4" />
          Network
        </Button>
        <Button
          variant={activeTab === 'analytics' ? 'default' : 'ghost'}
          size="sm"
          onClick={() => setActiveTab('analytics')}
          className="flex items-center gap-2"
        >
          <BarChart3 className="w-4 h-4" />
          Analytics
        </Button>
        <Button
          variant={activeTab === 'insights' ? 'default' : 'ghost'}
          size="sm"
          onClick={() => setActiveTab('insights')}
          className="flex items-center gap-2"
        >
          <TrendingUp className="w-4 h-4" />
          Insights
        </Button>
      </div>

      {/* Network tab */}
      {activeTab === 'network' && (
        <GraphVisualization />
      )}

      {/* Analytics tab */}
      {activeTab === 'analytics' && (
        <div className="space-y-6">
          {/* Overview stats */}
          {stats && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-slate-600">Total Nodes</p>
                      <p className="text-3xl font-bold">{stats.totalNodes}</p>
                    </div>
                    <Network className="w-8 h-8 text-blue-600" />
                  </div>
                </CardContent>
              </Card>
              
              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-slate-600">Connections</p>
                      <p className="text-3xl font-bold">{stats.totalEdges}</p>
                    </div>
                    <Network className="w-8 h-8 text-green-600" />
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-slate-600">Node Types</p>
                      <p className="text-3xl font-bold">{Object.keys(stats.nodeTypes).length}</p>
                    </div>
                    <Filter className="w-8 h-8 text-purple-600" />
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-slate-600">Density</p>
                      <p className="text-3xl font-bold">
                        {stats.totalNodes > 0 ? ((stats.totalEdges / (stats.totalNodes * (stats.totalNodes - 1))) * 100).toFixed(1) : 0}%
                      </p>
                    </div>
                    <TrendingUp className="w-8 h-8 text-orange-600" />
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Node type breakdown */}
          {stats && (
            <Card>
              <CardHeader>
                <CardTitle>Node Type Distribution</CardTitle>
                <CardDescription>Breakdown of entities by type</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {Object.entries(stats.nodeTypes).map(([type, count]) => (
                    <div key={type} className="flex items-center justify-between p-4 border rounded-lg">
                      <div className="flex items-center gap-3">
                        {getNodeTypeIcon(type)}
                        <div>
                          <p className="font-medium">{type}</p>
                          <p className="text-sm text-slate-600">{count as number} nodes</p>
                        </div>
                      </div>
                      <Badge className={getNodeTypeColor(type)}>
                        {((count as number / stats.totalNodes) * 100).toFixed(1)}%
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Centrality analysis */}
          {centralityData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Centrality Analysis</CardTitle>
                <CardDescription>Most connected nodes in the network</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {centralityData.slice(0, 10).map((item, index) => (
                    <div key={item.id} className="flex items-center justify-between p-3 border rounded-lg">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-blue-100 text-blue-800 rounded-full flex items-center justify-center text-sm font-medium">
                          {index + 1}
                        </div>
                        <div>
                          <p className="font-medium">{item.id}</p>
                          <p className="text-sm text-slate-600">Degree: {item.degree}</p>
                        </div>
                      </div>
                      <Badge variant="secondary">
                        {((item.degree / Math.max(...centralityData.map(c => c.degree))) * 100).toFixed(1)}%
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Insights tab */}
      {activeTab === 'insights' && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Network Insights</CardTitle>
              <CardDescription>AI-powered analysis of network patterns</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="p-4 bg-blue-50 rounded-lg">
                  <h4 className="font-medium text-blue-900 mb-2">Key Findings</h4>
                  <ul className="text-sm text-blue-800 space-y-1">
                    <li>• Network shows {stats?.totalNodes || 0} entities with {stats?.totalEdges || 0} connections</li>
                    <li>• Most active entity type: {stats ? Object.entries(stats.nodeTypes).sort(([,a], [,b]) => (b as number) - (a as number))[0]?.[0] : 'N/A'}</li>
                    <li>• Network density: {stats?.totalNodes > 0 ? ((stats.totalEdges / (stats.totalNodes * (stats.totalNodes - 1))) * 100).toFixed(1) : 0}%</li>
                  </ul>
                </div>

                <div className="p-4 bg-green-50 rounded-lg">
                  <h4 className="font-medium text-green-900 mb-2">Recommendations</h4>
                  <ul className="text-sm text-green-800 space-y-1">
                    <li>• Focus investigation on highly connected nodes</li>
                    <li>• Analyze communication patterns between key entities</li>
                    <li>• Look for isolated nodes that might indicate hidden connections</li>
                  </ul>
                </div>

                <div className="p-4 bg-orange-50 rounded-lg">
                  <h4 className="font-medium text-orange-900 mb-2">Next Steps</h4>
                  <ul className="text-sm text-orange-800 space-y-1">
                    <li>• Run timeline analysis on key communication channels</li>
                    <li>• Investigate nodes with unusual connection patterns</li>
                    <li>• Export network data for further analysis</li>
                  </ul>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Community detection results */}
          {communityData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Community Detection</CardTitle>
                <CardDescription>Identified groups and clusters in the network</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {communityData.slice(0, 5).map((community, index) => (
                    <div key={community.id} className="p-3 border rounded-lg">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-medium">Community {index + 1}</h4>
                        <Badge variant="outline">{community.community.length} members</Badge>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {community.community.slice(0, 5).map((member: string) => (
                          <Badge key={member} variant="secondary" className="text-xs">
                            {member}
                          </Badge>
                        ))}
                        {community.community.length > 5 && (
                          <Badge variant="secondary" className="text-xs">
                            +{community.community.length - 5} more
                          </Badge>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}
