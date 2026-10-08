"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Checkbox } from "@/components/ui/checkbox"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
} from "@/components/ui/sidebar"
import { Seal } from "@/components/brand/Seal"
import { Send, Plus, Files, ChevronsRightLeft } from "lucide-react"
import Link from "next/link"

const mockChatHistory = [
  { id: 1, title: "Deleted WhatsApp Messages..." },
  { id: 2, title: "Financial Transaction Analysis..." },
  { id: 3, title: "Connections of 'John Smith'..." },
  { id: 4, title: "Recurring Crypto Wallets" },
  { id: 5, title: "Codename 'Project Nightingale' Search" },
]

const mockMessages = [
  {
    type: "ai",
    text: "Welcome to the Master Investigation terminal. I can search for patterns and connections across all cases in the database. How can I assist you?",
  },
]

const mockCases = [
  { id: "case-001", name: "Case #001 - Mobile Extraction" },
  { id: "case-002", name: "Case #002 - Drive Image" },
  { id: "case-003", name: "Case #003 - Network Traffic" },
  { id: "case-004", name: "Case #004 - Financial Fraud" },
]

const suggestedPrompts = [
  "Are there any contacts shared between Case #001 and Case #004?",
  "List all financial transactions involving Bitcoin wallets across all cases.",
  "Identify location overlaps for subjects in cases #002 and #003 during Sep 2025.",
  "Search all documents for the codename 'Project Nightingale'.",
]

export default function GlobalSearchPage() {
  const [messages, setMessages] = useState(mockMessages)
  const [input, setInput] = useState("")
  const [selectedCases, setSelectedCases] = useState<string[]>([])
  const [activeChatId, setActiveChatId] = useState(1)

  const handleCaseSelection = (caseId: string) => {
    setSelectedCases((prev) =>
      prev.includes(caseId) ? prev.filter((id) => id !== caseId) : [...prev, caseId],
    )
  }

  const handleSendMessage = () => {
    if (!input.trim()) return
    const userMessage = { type: "user", text: input }
    setMessages((prev) => [...prev, userMessage])
    setInput("")

    setTimeout(() => {
      const scope =
        selectedCases.length > 0
          ? `Searching in ${selectedCases.length} selected case(s)...`
          : "Searching across the entire database..."
      const aiResponse = {
        type: "ai",
        text: `${scope}\n\nHere are the findings related to your query.`,
      }
      setMessages((prev) => [...prev, aiResponse])
    }, 1500)
  }

  return (
    <div className="flex flex-col h-screen">
      <div className="flex-1 flex overflow-hidden">
        <SidebarProvider>
          <Sidebar className="pt-4 bg-sidebar">
            <SidebarHeader className="flex flex-col items-center gap-3 mb-4">
              <div className="flex items-center gap-2">
                <Seal size={28} />
                <Link href="/"><span className="text-lg font-medium text-foreground">CiteSpan</span>
              </Link>
                </div>
              <Button
                variant="outline"
                className="w-full justify-start bg-transparent"
              >
                <Plus className="w-4 h-4 mr-2" /> New Investigation
              </Button>
            </SidebarHeader>
            <SidebarContent className="p-2">
              <p className="text-sm font-semibold text-foreground px-3 mb-2">History</p>
              <SidebarMenu>
                {mockChatHistory.map((chat) => (
                  <SidebarMenuItem key={chat.id}>
                    <SidebarMenuButton
                      onClick={() => setActiveChatId(chat.id)}
                      isActive={activeChatId === chat.id}
                      className="font-medium truncate"
                    >
                      {chat.title}
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarContent>
          </Sidebar>

          <SidebarInset>
            <div className="flex flex-col h-full">
              <header className="flex h-16 shrink-0 items-center gap-4 border-b px-4 bg-card/80 backdrop-blur-sm">
                <SidebarTrigger className="-ml-1" />
                <h2 className="text-lg font-semibold text-foreground">
                  {mockChatHistory.find((c) => c.id === activeChatId)?.title ||
                    "Master Investigation"}
                </h2>
                <div className="ml-auto">
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button variant="outline" className="bg-transparent">
                        <Files className="w-4 h-4 mr-2" />
                        {selectedCases.length > 0
                          ? `${selectedCases.length} Case(s) Selected`
                          : "All Cases"}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-80" align="end">
                      <div className="p-2">
                        <h4 className="font-medium leading-none mb-2">Case Scope</h4>
                        <p className="text-sm text-muted-foreground mb-4">
                          Select cases to query.
                        </p>
                        <ScrollArea className="h-48">
                          <div className="space-y-3">
                            {mockCases.map((c) => (
                              <label
                                key={c.id}
                                htmlFor={c.id}
                                className="flex items-center gap-3 p-2 rounded-md hover:bg-surface-3 cursor-pointer"
                              >
                                <Checkbox
                                  id={c.id}
                                  checked={selectedCases.includes(c.id)}
                                  onCheckedChange={() => handleCaseSelection(c.id)}
                                />
                                <span className="text-sm font-medium text-foreground">
                                  {c.name}
                                </span>
                              </label>
                            ))}
                          </div>
                        </ScrollArea>
                      </div>
                    </PopoverContent>
                  </Popover>
                </div>
              </header>

              {/* chat area */}
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="flex-1 overflow-y-auto p-6">
                  <div className="max-w-3xl mx-auto space-y-8">
                    {messages.map((msg, index) => (
                      <div
                        key={index}
                        className={`flex ${
                          msg.type === "ai" ? "justify-start" : "justify-end"
                        }`}
                      >
                        <div
                          className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                            msg.type === "ai"
                              ? "bg-surface-1 border text-foreground"
                              : "bg-primary text-primary-foreground"
                          }`}
                        >
                          <p className="text-sm leading-relaxed whitespace-pre-wrap">
                            {msg.text}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* predefined Q&A */}
                <div className="p-4 bg-card/80 backdrop-blur-sm border-t">
                  <div className="max-w-3xl mx-auto">
                    <div className="grid grid-cols-2 gap-2 mb-2">
                      {suggestedPrompts.map((prompt, i) => (
                        <button
                          key={i}
                          onClick={() => setInput(prompt)}
                          className="text-xs text-left bg-surface-2 text-muted-foreground p-2.5 rounded-lg hover:bg-surface-3 transition-colors"
                        >
                          <ChevronsRightLeft className="w-3 h-3 inline-block mr-2 text-signal" />
                          {prompt}
                        </button>
                      ))}
                    </div>
                    <div className="relative">
                      <Input
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyPress={(e) => e.key === "Enter" && handleSendMessage()}
                        placeholder="Ask a question across all cases..."
                        className="w-full py-6 pl-4 pr-14 text-base rounded-lg focus-visible:ring-signal/50"
                      />
                      <Button
                        onClick={handleSendMessage}
                        size="icon"
                        variant="signal"
                        className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full"
                      >
                        <Send className="w-5 h-5" />
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </SidebarInset>
        </SidebarProvider>
      </div>
    </div>
  )
}
