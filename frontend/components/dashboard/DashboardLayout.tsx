"use client"

import { useState } from "react"
import Link from "next/link"
import { Shield } from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { ChatMessage, menuItems, mockChatMessages } from "./data"
import { SidebarNav } from "./SidebarNav"
import { AiAssistantView } from "./views/AiAssistantView"
import { EvidenceSearchView } from "./views/EvidenceSearchView"
import { TimelineAnalysisView } from "./views/TimelineAnalysisView"
import { ReportsAnalyticsView } from "./views/ReportAnalyticsView"
import { DataVisualizationView } from "./views/DataVisualizationView"
import { GraphAnalysisView } from "./views/GraphAnalysisView"

export function DashboardLayout() {
  const [activeContent, setActiveContent] = useState("ai-assistant")
  const [chatInput, setChatInput] = useState("")
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(mockChatMessages)
  const [isSending, setIsSending] = useState(false)

  const handleSendMessage = async () => {
    const trimmedInput = chatInput.trim()
    if (!trimmedInput || isSending) return

    // Retrieve the run_id from local storage for the API call.
    const runId = localStorage.getItem("run_id")
    if (!runId) {
      alert("Error: No active analysis session found. Please upload a file first.")
      return
    }

    setIsSending(true)

  
    const userMessage: ChatMessage = {
      id: Date.now(), // Use a more unique ID
      type: "user",
      message: trimmedInput,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    }

  
    const loadingMessageId = Date.now() + 1
    const loadingMessage: ChatMessage = {
      id: loadingMessageId,
      type: "assistant",
      message: "",
      isLoading: true,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    }

    setChatMessages(prev => [...prev, userMessage, loadingMessage])
    setChatInput("")

    try {
    
      const response = await fetch("http://localhost:8000/query/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: trimmedInput,
          run_id: runId,
          provider: "openrouter",
          generate_insights: true,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.message || "Network response was not ok.")
      }

      const data = await response.json()

      const aiResponse: ChatMessage = {
        id: loadingMessageId,
        type: "assistant",
        message: data.insights || "No insights found.",
        isLoading: false,
        results: data.results,
        result_count: data.result_count,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      }

      
      setChatMessages(prev => prev.map(msg => (msg.id === loadingMessageId ? aiResponse : msg)))
    } catch (error:any) {
      console.error("Failed to fetch AI response:", error)
      const errorMessage: ChatMessage = {
        id: loadingMessageId,
        type: "assistant",
        message: `Sorry, an error occurred: ${error.message}`,
        isLoading: false,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      }
      setChatMessages(prev => prev.map(msg => (msg.id === loadingMessageId ? errorMessage : msg)))
    } finally {
      setIsSending(false)
    }
  }

  const renderContent = () => {
    switch (activeContent) {
      case "ai-assistant":
        return (
          <AiAssistantView
            chatMessages={chatMessages}
            chatInput={chatInput}
            isSending={isSending}
            setChatInput={setChatInput}
            handleSendMessage={handleSendMessage}
          />
        )
      case "evidence-search":
        return <EvidenceSearchView />
      case "timeline-analysis":
        return <TimelineAnalysisView />
      case "reports-analytics":
        return <ReportsAnalyticsView />
      case "data-visualization":
        return <DataVisualizationView />
      case "graph-analysis":
        return <GraphAnalysisView />
      default:
        return <div>Select a menu item</div>
    }
  }

  return (
    <SidebarProvider>
      <div className="flex h-screen w-full bg-white">
        <Sidebar>
          <SidebarHeader>
            <div className="flex items-center gap-2 p-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-purple-600 to-purple-800">
                <Shield className="h-4 w-4 text-white" />
              </div>
              <Link href="/">
                <span className="text-sm font-medium">ForensicAI</span>
              </Link>
            </div>
          </SidebarHeader>
          <SidebarContent>
            <SidebarNav menuItems={menuItems} activeContent={activeContent} setActiveContent={setActiveContent} />
          </SidebarContent>
          <SidebarFooter>
            <div className="p-2">
              <div className="text-sm font-medium">Case-2025-001</div>
            </div>
          </SidebarFooter>
        </Sidebar>

        <SidebarInset>
          <header className="flex h-16 shrink-0 items-center gap-2 border-b bg-white px-4">
            <SidebarTrigger className="-ml-1" />
          </header>
          <main className="flex-1 overflow-auto p-6">{renderContent()}</main>
        </SidebarInset>
      </div>
    </SidebarProvider>
  )
}