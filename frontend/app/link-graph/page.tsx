"use client"

// Cross-case entity link-graph surface.
// Force-directed (vis-network barnesHut) graph of how entities relate within and
// across cases. Every edge is provenance-cited; cross-case PII stays salted-hash;
// the view is time-filterable; the graph can be exported as a signed artifact.
import { useCallback, useEffect, useRef, useState } from "react"
import { Network } from "vis-network"
import { DataSet } from "vis-data"
import {
  AlertTriangle,
  Download,
  FileText,
  Loader2,
  Lock,
  Network as NetworkIcon,
  Search,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  exportLinkGraph,
  getLinkGraph,
  type LinkEdge,
  type LinkGraphParams,
  type LinkGraphResponse,
  type LinkNode,
} from "@/lib/linkGraphApi"

const TYPE_COLOR: Record<string, string> = {
  phone: "#2563eb",
  email: "#7c3aed",
  other: "#64748b",
}

function nodeColor(n: LinkNode, seedId: string | null) {
  if (n.id === seedId) return { background: "#f59e0b", border: "#b45309" }
  if (n.redacted) return { background: "#cbd5e1", border: "#475569" } // cross-case PII
  const c = TYPE_COLOR[n.type] ?? TYPE_COLOR.other
  return { background: c, border: c }
}

function nodeLabel(n: LinkNode) {
  if (n.redacted) return `🔒 ${n.id.slice(0, 8)}…`
  return n.label || n.value || n.id.slice(0, 8)
}

export default function LinkGraphPage() {
  const networkRef = useRef<HTMLDivElement>(null)
  const networkInstance = useRef<Network | null>(null)

  const [runIdsRaw, setRunIdsRaw] = useState("")
  const [seed, setSeed] = useState("")
  const [hops, setHops] = useState(2)
  const [start, setStart] = useState("")
  const [end, setEnd] = useState("")

  const [graph, setGraph] = useState<LinkGraphResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<LinkNode | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<LinkEdge | null>(null)

  const currentParams = useCallback((): LinkGraphParams => {
    const runIds = runIdsRaw
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    return {
      runIds,
      seed: seed.trim() || undefined,
      hops,
      start: start ? new Date(start).toISOString() : undefined,
      end: end ? new Date(end).toISOString() : undefined,
    }
  }, [runIdsRaw, seed, hops, start, end])

  const load = useCallback(async () => {
    const params = currentParams()
    if (params.runIds.length === 0) {
      setError("Enter at least one case run id.")
      return
    }
    setLoading(true)
    setError(null)
    setSelectedNode(null)
    setSelectedEdge(null)
    try {
      const data = await getLinkGraph(params)
      setGraph(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load graph")
      setGraph(null)
    } finally {
      setLoading(false)
    }
  }, [currentParams])

  const doExport = useCallback(
    async (format: "json" | "pdf") => {
      const params = currentParams()
      if (params.runIds.length === 0) return
      setExporting(true)
      setError(null)
      try {
        const blob = await exportLinkGraph(params, format)
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = format === "pdf" ? "link_graph.pdf" : "link_graph.signed.json"
        a.click()
        URL.revokeObjectURL(url)
      } catch (e) {
        setError(e instanceof Error ? e.message : "Export failed")
      } finally {
        setExporting(false)
      }
    },
    [currentParams],
  )

  // Render the graph with a force-directed layout whenever data changes.
  useEffect(() => {
    if (!networkRef.current || !graph) return
    const seedId = graph.seed_id
    const nodes = new DataSet(
      graph.nodes.map((n) => ({
        id: n.id,
        label: nodeLabel(n),
        color: nodeColor(n, seedId),
        value: n.degree + 1,
        shape: "dot",
        font: { size: 13, color: "#0f172a" },
      })),
    )
    const edges = new DataSet(
      graph.edges.map((e, i) => ({
        id: i,
        from: e.source,
        to: e.target,
        value: e.weight,
        title: `${e.weight} interaction(s), ${e.citations_shown} shown`,
        color: { color: "#94a3b8", highlight: "#0ea5e9" },
      })),
    )
    const network = new Network(
      networkRef.current,
      { nodes, edges },
      {
        nodes: { scaling: { min: 8, max: 40 }, borderWidth: 2 },
        edges: {
          scaling: { min: 1, max: 8 },
          smooth: { enabled: true, type: "continuous", roundness: 0.5 },
        },
        physics: {
          solver: "barnesHut",
          stabilization: { iterations: 150 },
          barnesHut: { gravitationalConstant: -3000, springLength: 110 },
        },
        interaction: { hover: true, tooltipDelay: 150 },
      },
    )
    networkInstance.current = network

    network.on("selectNode", (p) => {
      const n = graph.nodes.find((x) => x.id === p.nodes[0])
      setSelectedNode(n ?? null)
      setSelectedEdge(null)
    })
    network.on("selectEdge", (p) => {
      if (p.nodes.length) return // node selection takes precedence
      const e = graph.edges[p.edges[0] as number]
      setSelectedEdge(e ?? null)
      setSelectedNode(null)
    })
    network.on("deselectNode", () => setSelectedNode(null))

    return () => network.destroy()
  }, [graph])

  return (
    <div className="mx-auto max-w-7xl p-6">
      <header className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900">
          <NetworkIcon className="h-6 w-6 text-blue-600" />
          Cross-Case Entity Link Graph
        </h1>
        <p className="text-slate-600">
          Provenance-cited network of entities across cases. Every edge traces to
          its source rows; identifiers seen in 2+ cases stay salted-hash.
        </p>
      </header>

      {/* Controls */}
      <Card className="mb-6">
        <CardContent className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2 lg:grid-cols-6">
          <div className="lg:col-span-2">
            <label className="text-xs font-medium text-slate-600">
              Case run id(s) — comma/space separated
            </label>
            <Input
              value={runIdsRaw}
              onChange={(e) => setRunIdsRaw(e.target.value)}
              placeholder="run-uuid-1, run-uuid-2"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600">
              Seed (optional)
            </label>
            <Input
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="+91XXXX"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600">Hops</label>
            <Input
              type="number"
              min={0}
              max={6}
              value={hops}
              onChange={(e) => setHops(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600">From</label>
            <Input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600">To</label>
            <Input
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </div>
          <div className="flex items-end gap-2 lg:col-span-6">
            <Button onClick={load} disabled={loading}>
              {loading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Search className="mr-2 h-4 w-4" />
              )}
              Build graph
            </Button>
            <Button
              variant="outline"
              disabled={!graph || exporting}
              onClick={() => doExport("json")}
            >
              <Download className="mr-2 h-4 w-4" /> Signed JSON
            </Button>
            <Button
              variant="outline"
              disabled={!graph || exporting}
              onClick={() => doExport("pdf")}
            >
              <FileText className="mr-2 h-4 w-4" /> Signed PDF
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p className="whitespace-pre-wrap break-words font-mono text-xs">
            {error}
          </p>
        </div>
      )}

      {graph && (
        <>
          <div className="mb-4 flex flex-wrap gap-3 text-sm">
            <Badge variant="secondary">{graph.node_count} entities</Badge>
            <Badge variant="secondary">{graph.edge_count} relations</Badge>
            <Badge variant="secondary">{graph.run_ids.length} case(s)</Badge>
            {graph.seed && !graph.seed_found && (
              <Badge variant="destructive">seed not found in scope</Badge>
            )}
            {graph.excluded_events > 0 && (
              <Badge variant="outline">
                {graph.excluded_events} event(s) excluded (no timestamp)
              </Badge>
            )}
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle>Network</CardTitle>
                <CardDescription>
                  Drag to explore · click a node or edge for details &amp;
                  provenance
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div
                  ref={networkRef}
                  className="w-full rounded-lg border"
                  style={{ height: 560 }}
                />
              </CardContent>
            </Card>

            <Card className="lg:col-span-1">
              <CardHeader>
                <CardTitle className="text-base">
                  {selectedEdge
                    ? "Relation provenance"
                    : selectedNode
                      ? "Entity"
                      : "Details"}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {selectedNode && (
                  <NodeDetails node={selectedNode} seedId={graph.seed_id} />
                )}
                {selectedEdge && <EdgeDetails edge={selectedEdge} />}
                {!selectedNode && !selectedEdge && (
                  <p className="py-8 text-center text-slate-500">
                    Select a node or edge.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}

function NodeDetails({
  node,
  seedId,
}: {
  node: LinkNode
  seedId: string | null
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {node.redacted ? (
          <Lock className="h-4 w-4 text-slate-500" />
        ) : (
          <NetworkIcon className="h-4 w-4 text-blue-600" />
        )}
        <span className="font-medium">
          {node.redacted ? "Cross-case (redacted)" : node.label || node.value}
        </span>
        {node.id === seedId && <Badge>seed</Badge>}
      </div>
      <Row k="Type" v={node.type} />
      {node.redacted ? (
        <p className="text-xs text-slate-500">
          Appears in {node.case_count} cases — raw value withheld; referenced by
          salted hash.
        </p>
      ) : (
        <Row k="Identifier" v={node.value ?? "—"} />
      )}
      <Row k="Degree" v={String(node.degree)} />
      <Row k="In cases" v={String(node.case_count)} />
      {node.hops !== null && <Row k="Hops from seed" v={String(node.hops)} />}
      <Row k="Hash id" v={node.id} mono />
    </div>
  )
}

function EdgeDetails({ edge }: { edge: LinkEdge }) {
  return (
    <div className="space-y-2">
      <Row k="Weight" v={`${edge.weight} interaction(s)`} />
      <Row
        k="Source rows"
        v={
          edge.citations_truncated
            ? `showing ${edge.citations_shown} of ${edge.weight}`
            : `${edge.weight}`
        }
      />
      <div className="max-h-80 space-y-2 overflow-y-auto">
        {edge.citations.map((c, i) => (
          <div key={i} className="rounded border bg-slate-50 p-2 text-xs">
            <div className="font-medium">{c.source_table}</div>
            <div className="font-mono text-[10px] text-slate-500">
              run {c.run_id.slice(0, 8)} · row {c.row_id.slice(0, 12)}
            </div>
            <div className="text-slate-600">{c.timestamp ?? "no timestamp"}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div>
      <span className="text-xs font-medium text-slate-500">{k}</span>
      <p className={mono ? "break-all font-mono text-xs" : "text-sm"}>{v}</p>
    </div>
  )
}
