"use client"

import { GraphVisualization } from "@/components/graph/GraphVisualization"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { graphApi } from "@/lib/api/graph-api"
import { useState, useEffect } from "react"
import { RefreshCw, Database, Network, Users, MessageSquare, Phone } from "lucide-react"

export default function GraphTestPage() {
  const [connectionStatus, setConnectionStatus] = useState<'checking' | 'connected' | 'error'>('checking')
  const [error, setError] = useState<string | null>(null)
  const [sampleData, setSampleData] = useState<any>(null)

  // Test connection and load sample data
  useEffect(() => {
    testConnection()
  }, [])

  const testConnection = async () => {
    try {
      setConnectionStatus('checking')
      setError(null)
      
      // Try to get full graph data
      const data = await graphApi.getFullGraph()
      setSampleData(data)
      setConnectionStatus('connected')
    } catch (err) {
      setConnectionStatus('error')
      setError(err instanceof Error ? err.message : 'Failed to connect to Neo4j')
    }
  }

  const addSampleData = async () => {
    try {
      const samplePeople = [
        { id: "P1", name: "Alice Johnson" },
        { id: "P2", name: "Bob Smith" },
        { id: "P3", name: "Charlie Brown" },
        { id: "P4", name: "Diana Prince" },
      ]

      const sampleMessages = [
        { id: "M1", content: "Hello Bob, how are you?", timestamp: "2025-01-15T10:00:00" },
        { id: "M2", content: "Meeting at 3 PM", timestamp: "2025-01-15T14:30:00" },
        { id: "M3", content: "Thanks for the update", timestamp: "2025-01-15T16:45:00" },
      ]

      const sampleCalls = [
        { id: "C1", caller: "P1", receiver: "P2", duration: 300 },
        { id: "C2", caller: "P2", receiver: "P3", duration: 180 },
        { id: "C3", caller: "P3", receiver: "P4", duration: 420 },
      ]

      const sampleRelationships = [
        { from_id: "P1", to_id: "M1", type: "SENT" },
        { from_id: "P2", to_id: "M2", type: "SENT" },
        { from_id: "P3", to_id: "M3", type: "SENT" },
        { from_id: "P1", to_id: "P2", type: "CALLED" },
        { from_id: "P2", to_id: "P3", type: "CALLED" },
        { from_id: "P3", to_id: "P4", type: "CALLED" },
      ]

      await graphApi.batchIngest({
        people: samplePeople,
        messages: sampleMessages,
        calls: sampleCalls,
        relationships: sampleRelationships,
      })

      // Refresh the graph
      testConnection()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add sample data')
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-slate-900">Graph Integration Test</h1>
            <p className="text-slate-600">Testing Neo4j integration with frontend visualization</p>
          </div>
          <div className="flex items-center gap-4">
            <Button onClick={testConnection} variant="outline">
              <RefreshCw className="w-4 h-4 mr-2" />
              Test Connection
            </Button>
            <Button onClick={addSampleData} variant="default">
              <Database className="w-4 h-4 mr-2" />
              Add Sample Data
            </Button>
          </div>
        </div>

        {/* Connection Status */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="w-5 h-5" />
              Backend Connection Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-4">
              {connectionStatus === 'checking' && (
                <>
                  <RefreshCw className="w-5 h-5 animate-spin text-blue-600" />
                  <span className="text-blue-600">Checking connection...</span>
                </>
              )}
              {connectionStatus === 'connected' && (
                <>
                  <div className="w-5 h-5 bg-green-500 rounded-full"></div>
                  <span className="text-green-600">Connected to Neo4j backend</span>
                </>
              )}
              {connectionStatus === 'error' && (
                <>
                  <div className="w-5 h-5 bg-red-500 rounded-full"></div>
                  <span className="text-red-600">Connection failed</span>
                </>
              )}
            </div>
            {error && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
                <p className="text-red-800 text-sm">{error}</p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Sample Data Stats */}
        {sampleData && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-slate-600">Total Nodes</p>
                    <p className="text-2xl font-bold">{sampleData.nodes?.length || 0}</p>
                  </div>
                  <Network className="w-8 h-8 text-blue-600" />
                </div>
              </CardContent>
            </Card>
            
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-slate-600">Connections</p>
                    <p className="text-2xl font-bold">{sampleData.edges?.length || 0}</p>
                  </div>
                  <Network className="w-8 h-8 text-green-600" />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-slate-600">People</p>
                    <p className="text-2xl font-bold">
                      {sampleData.nodes?.filter((n: any) => n.label === 'Person').length || 0}
                    </p>
                  </div>
                  <Users className="w-8 h-8 text-purple-600" />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-slate-600">Messages</p>
                    <p className="text-2xl font-bold">
                      {sampleData.nodes?.filter((n: any) => n.label === 'Message').length || 0}
                    </p>
                  </div>
                  <MessageSquare className="w-8 h-8 text-orange-600" />
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Graph Visualization */}
        {connectionStatus === 'connected' && (
          <GraphVisualization />
        )}

        {/* Instructions */}
        <Card>
          <CardHeader>
            <CardTitle>Integration Instructions</CardTitle>
            <CardDescription>How to test the Neo4j integration</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div>
                <h4 className="font-medium mb-2">1. Backend Setup</h4>
                <p className="text-sm text-slate-600 mb-2">
                  Make sure the backend is running with Neo4j integration:
                </p>
                <div className="bg-slate-100 p-3 rounded-lg font-mono text-sm">
                  cd backend<br/>
                  python server.py
                </div>
              </div>

              <div>
                <h4 className="font-medium mb-2">2. Neo4j Configuration</h4>
                <p className="text-sm text-slate-600 mb-2">
                  Ensure your .env file has the correct Neo4j Aura credentials.
                </p>
              </div>

              <div>
                <h4 className="font-medium mb-2">3. Test Steps</h4>
                <ul className="text-sm text-slate-600 space-y-1">
                  <li>• Click "Test Connection" to verify backend connectivity</li>
                  <li>• Click "Add Sample Data" to populate the graph with test data</li>
                  <li>• Use the interactive graph to explore relationships</li>
                  <li>• Navigate to Dashboard → Graph Analysis for full features</li>
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
