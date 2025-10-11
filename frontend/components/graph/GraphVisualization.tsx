"use client"

import { useEffect, useRef, useState } from 'react'
import { Network } from 'vis-network'
import { DataSet } from 'vis-data'
import { graphApi, GraphData, graphUtils } from '@/lib/api/graph-api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { 
  Network as NetworkIcon, 
  RefreshCw, 
  Filter, 
  Search, 
  Download,
  Users,
  MessageSquare,
  Phone
} from 'lucide-react'

interface GraphVisualizationProps {
  className?: string
}

export function GraphVisualization({ className }: GraphVisualizationProps) {
  const networkRef = useRef<HTMLDivElement>(null)
  const networkInstance = useRef<Network | null>(null)
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<any>(null)
  const [stats, setStats] = useState<any>(null)
  const [filterType, setFilterType] = useState<string>('all')

  // Load graph data
  const loadGraphData = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await graphApi.getFullGraph()
      setGraphData(data)
      
      // Calculate stats
      const nodeStats = graphUtils.getNodeStats(data)
      setStats(nodeStats)
      
      // Initialize network
      if (networkRef.current && data) {
        initializeNetwork(data)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph data')
    } finally {
      setLoading(false)
    }
  }

  // Initialize vis-network
  const initializeNetwork = (data: GraphData) => {
    if (!networkRef.current) return

    const transformedData = graphUtils.transformForVisNetwork(data)
    
    const nodes = new DataSet(transformedData.nodes)
    const edges = new DataSet(transformedData.edges)

    const options = {
      nodes: {
        shape: 'dot',
        size: 16,
        font: {
          size: 14,
          color: '#343434'
        },
        borderWidth: 2,
        shadow: true,
        color: {
          border: '#2B7CE9',
          background: '#97C2FC',
          highlight: {
            border: '#2B7CE9',
            background: '#D2E5FF'
          }
        }
      },
      edges: {
        width: 2,
        color: { color: '#848484', highlight: '#848484' },
        smooth: {
          type: 'continuous'
        }
      },
      physics: {
        stabilization: { iterations: 100 },
        barnesHut: {
          gravitationalConstant: -2000,
          centralGravity: 0.3,
          springLength: 95,
          springConstant: 0.04,
          damping: 0.09,
          avoidOverlap: 0.1
        }
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
        hideEdgesOnDrag: true
      }
    }

    const network = new Network(networkRef.current, { nodes, edges }, options)
    networkInstance.current = network

    // Add event listeners
    network.on('selectNode', (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0]
        const node = nodes.get(nodeId)
        setSelectedNode(node)
      }
    })

    network.on('deselectNode', () => {
      setSelectedNode(null)
    })
  }

  // Filter nodes by type
  const filterNodes = (nodeType: string) => {
    if (!graphData) return
    
    setFilterType(nodeType)
    
    if (nodeType === 'all') {
      loadGraphData()
    } else {
      const filteredData = graphUtils.filterNodesByType(graphData, nodeType)
      if (networkRef.current) {
        initializeNetwork(filteredData)
      }
    }
  }

  // Get node type icon
  const getNodeTypeIcon = (nodeType: string) => {
    switch (nodeType.toLowerCase()) {
      case 'person':
        return <Users className="w-4 h-4" />
      case 'message':
        return <MessageSquare className="w-4 h-4" />
      case 'call':
        return <Phone className="w-4 h-4" />
      default:
        return <NetworkIcon className="w-4 h-4" />
    }
  }

  useEffect(() => {
    loadGraphData()
    
    return () => {
      if (networkInstance.current) {
        networkInstance.current.destroy()
      }
    }
  }, [])

  if (loading) {
    return (
      <Card className={className}>
        <CardContent className="flex items-center justify-center h-96">
          <div className="text-center">
            <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-slate-600" />
            <p className="text-slate-600">Loading graph data...</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className={className}>
        <CardContent className="flex items-center justify-center h-96">
          <div className="text-center">
            <div className="text-red-500 mb-4">Failed to load graph</div>
            <p className="text-slate-600 mb-4">{error}</p>
            <Button onClick={loadGraphData} variant="outline">
              <RefreshCw className="w-4 h-4 mr-2" />
              Retry
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className={className}>
      {/* Header with controls */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">Graph Network</h2>
          <p className="text-slate-600">Interactive visualization of entity relationships</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={loadGraphData}>
            <RefreshCw className="w-4 h-4 mr-2" />
            Refresh
          </Button>
          <Button variant="outline" size="sm">
            <Download className="w-4 h-4 mr-2" />
            Export
          </Button>
        </div>
      </div>

      {/* Stats and filters */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-slate-600">Total Nodes</p>
                  <p className="text-2xl font-semibold">{stats.totalNodes}</p>
                </div>
                <NetworkIcon className="w-8 h-8 text-blue-600" />
              </div>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-slate-600">Connections</p>
                  <p className="text-2xl font-semibold">{stats.totalEdges}</p>
                </div>
                <NetworkIcon className="w-8 h-8 text-green-600" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-slate-600">Node Types</p>
                  <p className="text-2xl font-semibold">{Object.keys(stats.nodeTypes).length}</p>
                </div>
                <Filter className="w-8 h-8 text-purple-600" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-slate-600">Filter</p>
                  <p className="text-sm font-medium">{filterType}</p>
                </div>
                <Search className="w-8 h-8 text-orange-600" />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Node type filters */}
      {stats && (
        <div className="flex flex-wrap gap-2 mb-6">
          <Button
            variant={filterType === 'all' ? 'default' : 'outline'}
            size="sm"
            onClick={() => filterNodes('all')}
          >
            All ({stats.totalNodes})
          </Button>
          {Object.entries(stats.nodeTypes).map(([type, count]) => (
            <Button
              key={type}
              variant={filterType === type ? 'default' : 'outline'}
              size="sm"
              onClick={() => filterNodes(type)}
              className="flex items-center gap-2"
            >
              {getNodeTypeIcon(type)}
              {type} ({count as number})
            </Button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Graph visualization */}
        <div className="lg:col-span-3">
          <Card>
            <CardHeader>
              <CardTitle>Network Visualization</CardTitle>
              <CardDescription>
                Interactive graph showing relationships between entities
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div 
                ref={networkRef} 
                className="w-full h-96 border rounded-lg"
                style={{ minHeight: '400px' }}
              />
            </CardContent>
          </Card>
        </div>

        {/* Node details panel */}
        <div className="lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle>Node Details</CardTitle>
              <CardDescription>
                {selectedNode ? 'Selected node information' : 'Click a node to view details'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {selectedNode ? (
                <div className="space-y-4">
                  <div>
                    <label className="text-sm font-medium text-slate-600">ID</label>
                    <p className="text-sm">{selectedNode.id}</p>
                  </div>
                  
                  <div>
                    <label className="text-sm font-medium text-slate-600">Type</label>
                    <div className="flex items-center gap-2 mt-1">
                      {getNodeTypeIcon(selectedNode.group)}
                      <Badge variant="secondary">{selectedNode.group}</Badge>
                    </div>
                  </div>

                  <div>
                    <label className="text-sm font-medium text-slate-600">Name</label>
                    <p className="text-sm">{selectedNode.label}</p>
                  </div>

                  {selectedNode.properties && Object.keys(selectedNode.properties).length > 0 && (
                    <div>
                      <label className="text-sm font-medium text-slate-600">Properties</label>
                      <div className="mt-1 space-y-1">
                        {Object.entries(selectedNode.properties).map(([key, value]) => (
                          <div key={key} className="text-xs">
                            <span className="font-medium">{key}:</span> {String(value)}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <Button 
                    size="sm" 
                    variant="outline" 
                    className="w-full"
                    onClick={() => {
                      console.log('Analyze node:', selectedNode.id)
                    }}
                  >
                    <Search className="w-4 h-4 mr-2" />
                    Analyze Node
                  </Button>
                </div>
              ) : (
                <div className="text-center text-slate-500 py-8">
                  <NetworkIcon className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p className="text-sm">Select a node to view details</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
