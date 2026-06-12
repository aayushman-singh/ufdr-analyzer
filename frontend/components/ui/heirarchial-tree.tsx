"use client"
import type React from "react"
import Tree from "react-d3-tree"
import { Database, FileText, HardDrive, Settings, Network, Clock, Hash, Shield } from "lucide-react"

interface TreeNode {
  name: string
  attributes?: {
    type?: string
    size?: string
    count?: number
    icon?: string
  }
  children?: TreeNode[]
}

interface HierarchicalTreeProps {
  data: any[]
  className?: string
}

const getIconComponent = (iconType: string) => {
  const iconMap: { [key: string]: React.ReactNode } = {
    database: <Database className="w-4 h-4" />,
    file: <FileText className="w-4 h-4" />,
    harddrive: <HardDrive className="w-4 h-4" />,
    settings: <Settings className="w-4 h-4" />,
    network: <Network className="w-4 h-4" />,
    clock: <Clock className="w-4 h-4" />,
    hash: <Hash className="w-4 h-4" />,
    shield: <Shield className="w-4 h-4" />,
  }
  return iconMap[iconType] || <FileText className="w-4 h-4" />
}

const transformDataForD3Tree = (data: any[]): TreeNode => {
  const transformNode = (node: any): TreeNode => {
    const transformed: TreeNode = {
      name: node.name,
      attributes: {
        type: node.type,
        size: node.size,
        count: node.count,
        icon: node.id,
      },
    }

    if (node.children && node.children.length > 0) {
      transformed.children = node.children.map(transformNode)
    }

    return transformed
  }

  return {
    name: "UFDR Case File",
    attributes: { type: "root", icon: "shield" },
    children: data.map(transformNode),
  }
}

const renderCustomNodeElement = ({ nodeDatum, toggleNode }: any) => {
  const isFolder = nodeDatum.children && nodeDatum.children.length > 0
  const nodeColor = isFolder ? "oklch(0.860 0.175 117)" : "oklch(0.700 0.090 235)"
  const textColor = "oklch(0.967 0.004 247)"

  return (
    <g>
      {/* Node circle */}
      <circle
        r={20}
        fill={nodeColor}
        stroke="#ffffff"
        strokeWidth={2}
        onClick={toggleNode}
        style={{ cursor: "pointer" }}
      />

      {/* Node icon */}
      <foreignObject x={-8} y={-8} width={16} height={16}>
        <div className="flex items-center justify-center text-white">
          {isFolder ? (
            <div className="w-3 h-3 bg-white rounded-sm opacity-80" />
          ) : (
            <div className="w-2 h-2 bg-white rounded-full" />
          )}
        </div>
      </foreignObject>

      {/* Node label */}
      <text
        fill={textColor}
        strokeWidth="0"
        x={25}
        y={5}
        fontSize="12"
        fontWeight="500"
        style={{ fontFamily: "system-ui, sans-serif" }}
      >
        {nodeDatum.name}
      </text>

      {/* Additional info */}
      {nodeDatum.attributes?.count && (
        <text
          fill="oklch(0.705 0.018 252)"
          strokeWidth="0"
          x={25}
          y={18}
          fontSize="10"
          style={{ fontFamily: "system-ui, sans-serif" }}
        >
          {nodeDatum.attributes.count.toLocaleString()} items
        </text>
      )}

      {nodeDatum.attributes?.size && (
        <text
          fill="oklch(0.705 0.018 252)"
          strokeWidth="0"
          x={25}
          y={18}
          fontSize="10"
          style={{ fontFamily: "system-ui, sans-serif" }}
        >
          {nodeDatum.attributes.size}
        </text>
      )}
    </g>
  )
}

export function HierarchicalTree({ data, className = "" }: HierarchicalTreeProps) {
  const treeData = transformDataForD3Tree(data)

  return (
    <div className={`w-full h-96 bg-card rounded-lg border border-border ${className}`}>
      <Tree
        data={treeData}
        orientation="vertical"
        translate={{ x: 200, y: 50 }}
        separation={{ siblings: 1.5, nonSiblings: 2 }}
        nodeSize={{ x: 200, y: 100 }}
        renderCustomNodeElement={renderCustomNodeElement}
        pathFunc="diagonal"
        initialDepth={2}
        collapsible={true}
        zoom={0.8}
        scaleExtent={{ min: 0.5, max: 2 }}
        enableLegacyTransitions={true}
      />
    </div>
  )
}
