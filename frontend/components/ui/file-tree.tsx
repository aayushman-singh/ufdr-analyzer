"use client"

import type React from "react"

import { useState } from "react"
import { ChevronRight, ChevronDown, Folder, FolderOpen, File } from "lucide-react"

interface TreeNode {
  id: string
  name: string
  type: "folder" | "file"
  icon?: React.ReactNode
  children?: TreeNode[]
  size?: string
  count?: number
}

interface FileTreeProps {
  data: TreeNode[]
  className?: string
}

const TreeItem = ({ node, level = 0 }: { node: TreeNode; level?: number }) => {
  const [isExpanded, setIsExpanded] = useState(level < 2) // Auto-expand first 2 levels

  const hasChildren = node.children && node.children.length > 0
  const paddingLeft = level * 20

  const getIcon = () => {
    if (node.icon) return node.icon
    if (node.type === "folder") {
      return isExpanded ? (
        <FolderOpen className="w-4 h-4 text-info" />
      ) : (
        <Folder className="w-4 h-4 text-info" />
      )
    }
    return <File className="w-4 h-4 text-muted-foreground" />
  }

  return (
    <div>
      <div
        className="flex items-center py-1 px-2 hover:bg-accent rounded cursor-pointer group"
        style={{ paddingLeft: `${paddingLeft + 8}px` }}
        onClick={() => hasChildren && setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center space-x-2 flex-1">
          {hasChildren && (
            <div className="w-4 h-4 flex items-center justify-center">
              {isExpanded ? (
                <ChevronDown className="w-3 h-3 text-muted-foreground" />
              ) : (
                <ChevronRight className="w-3 h-3 text-muted-foreground" />
              )}
            </div>
          )}
          {!hasChildren && <div className="w-4" />}

          {getIcon()}

          <span className="text-sm text-foreground font-medium">{node.name}</span>

          {node.count && (
            <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
              {node.count.toLocaleString()} items
            </span>
          )}

          {node.size && <span className="text-xs text-muted-foreground">{node.size}</span>}
        </div>
      </div>

      {hasChildren && isExpanded && (
        <div>
          {node.children!.map((child) => (
            <TreeItem key={child.id} node={child} level={level + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

export function FileTree({ data, className = "" }: FileTreeProps) {
  return (
    <div className={`bg-card border border-border rounded-lg overflow-hidden ${className}`}>
      <div className="bg-surface-1 px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-foreground">UFDR File Structure</h3>
      </div>
      <div className="p-2 max-h-96 overflow-y-auto">
        {data.map((node) => (
          <TreeItem key={node.id} node={node} />
        ))}
      </div>
    </div>
  )
}
