"use client"
import { useState } from "react"
import { Shield } from "lucide-react"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { menuItems, mockChatMessages, ChatMessage } from "./data"
import { SidebarNav } from "./SidebarNav"

// Import all your view components
import { AiAssistantView } from "./views/AiAssistantView"
import { EvidenceSearchView } from "./views/EvidenceSearchView"
import { TimelineAnalysisView } from "./views/TimelineAnalysisView"
import { ReportsAnalyticsView } from "./views/ReportAnalyticsView"
import { DataVisualizationView } from "./views/DataVisualizationView"
import Link from "next/link"


export function DashboardLayout() {
  const [activeContent, setActiveContent] = useState("ai-assistant")
  const [chatInput, setChatInput] = useState("")
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(mockChatMessages)

  const handleSendMessage = () => {
    if (!chatInput.trim()) return
    const newMessage = { id: chatMessages.length + 1, type: "user" as const, message: chatInput, timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) };
    setChatMessages([...chatMessages, newMessage]);
    setChatInput("");
    setTimeout(() => {
      const aiResponse = { id: chatMessages.length + 2, type: "assistant" as const, message: "I'm analyzing your request...", timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) };
      setChatMessages((prev) => [...prev, aiResponse]);
    }, 1000);
  }

  const renderContent = () => {
    switch (activeContent) {
      case "ai-assistant":
        return <AiAssistantView chatMessages={chatMessages} chatInput={chatInput} setChatInput={setChatInput} handleSendMessage={handleSendMessage} />
      case "evidence-search":
        return <EvidenceSearchView />
      case "timeline-analysis":
        return <TimelineAnalysisView />
      case "reports-analytics":
        return <ReportsAnalyticsView />
      case "data-visualization":
        return <DataVisualizationView />
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
                <div className="w-8 h-8 bg-gradient-to-br from-purple-600 to-purple-800 rounded-lg flex items-center justify-center">
                    <Shield className="w-4 h-4 text-white" />
                </div>
                <Link href="/"><span className="text-sm font-medium">ForensicAI</span>
            </Link>
                </div>
          </SidebarHeader>
          <SidebarContent>
            <SidebarGroup>
                <SidebarGroupLabel>Investigation Tools</SidebarGroupLabel>
                <SidebarGroupContent>
                    <SidebarNav menuItems={menuItems} activeContent={activeContent} setActiveContent={setActiveContent} />
                </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter>
            <div className="p-2">
                <div className="text-sm font-medium">Case-2024-001</div>
            </div>
          </SidebarFooter>
        </Sidebar>

        <SidebarInset>
          <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4 bg-white">
            <SidebarTrigger className="-ml-1" />
            {/* Breadcrumbs can go here */}
          </header>
          <main className="flex-1 overflow-auto p-6">{renderContent()}</main>
        </SidebarInset>
      </div>
    </SidebarProvider>
  )
}