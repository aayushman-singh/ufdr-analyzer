"use client"

import { useState, useRef, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Bot, ChevronDown, ChevronUp, Database, Send, User } from "lucide-react"
import { ChatMessage, predefinedQuestions } from "../data"

interface AiAssistantViewProps {
  chatMessages: ChatMessage[]
  chatInput: string
  isSending: boolean
  setChatInput: (value: string) => void
  handleSendMessage: () => void
}

export function AiAssistantView({
  chatMessages,
  chatInput,
  isSending,
  setChatInput,
  handleSendMessage,
}: AiAssistantViewProps) {
  const [expandedResultsId, setExpandedResultsId] = useState<number | null>(null)
  const chatContainerRef = useRef<HTMLDivElement>(null)

  // This effect runs whenever the chatMessages array changes.
  // It smoothly scrolls the chat container to the bottom to show the latest message.
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: "smooth",
      })
    }
  }, [chatMessages])

  const handleToggleResults = (messageId: number) => {
    setExpandedResultsId(prevId => (prevId === messageId ? null : messageId))
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="mb-2 text-4xl font-light tracking-tight text-slate-900">AI Assistant</h2>
        <p className="text-lg font-light text-slate-600">
          Ask questions about your forensic data in natural language
        </p>
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card className="flex h-[600px] flex-col">
            <CardHeader className="border-b bg-gradient-to-r from-purple-50 to-purple-100">
              <CardTitle className="flex items-center gap-2 font-medium text-slate-900">
                <Bot className="h-5 w-5 text-purple-600" />
                Forensic AI Chat
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col overflow-hidden p-0">
              {/* The ref is attached to the scrollable div here */}
              <div ref={chatContainerRef} className="flex-1 space-y-4 overflow-y-auto p-4">
                {chatMessages.map(msg => (
                  <div key={msg.id}>
                    <div className={`flex ${msg.type === "user" ? "justify-end" : "justify-start"}`}>
                      <div
                        className={`max-w-full break-words rounded-2xl px-4 py-3 md:max-w-[80%] ${
                          msg.type === "user"
                            ? "bg-slate-900 text-white"
                            : "bg-gradient-to-br from-purple-50 to-purple-100 text-slate-900"
                        }`}
                      >
                        {msg.isLoading ? (
                          <div className="flex items-center space-x-1 py-1">
                            <span className="h-2 w-2 animate-bounce rounded-full bg-slate-500 [animation-delay:-0.3s]"></span>
                            <span className="h-2 w-2 animate-bounce rounded-full bg-slate-500 [animation-delay:-0.15s]"></span>
                            <span className="h-2 w-2 animate-bounce rounded-full bg-slate-500"></span>
                          </div>
                        ) : (
                          <>
                            <p className="whitespace-pre-line text-sm leading-relaxed">{msg.message}</p>
                            {msg.type === "assistant" && msg.result_count && msg.result_count > 0 && (
                              <Button
                                variant="outline"
                                size="sm"
                                className="mt-3 flex items-center gap-2 border-purple-200 bg-white text-purple-700 hover:bg-purple-50 hover:text-purple-800"
                                onClick={() => handleToggleResults(msg.id)}
                              >
                                {expandedResultsId === msg.id ? (
                                  <>
                                    Hide Detailed Results <ChevronUp className="h-4 w-4" />
                                  </>
                                ) : (
                                  <>
                                    Show {msg.result_count} Detailed Results <ChevronDown className="h-4 w-4" />
                                  </>
                                )}
                              </Button>
                            )}
                          </>
                        )}
                      </div>
                    </div>

                    {/* Expandable Detailed Results Section */}
                    {expandedResultsId === msg.id && msg.results && (
                      <div className="mt-2 rounded-lg border bg-white p-4">
                        <h4 className="mb-2 flex items-center gap-2 text-base font-semibold text-slate-800">
                          <Database className="h-4 w-4 text-slate-500" /> Detailed Evidence
                        </h4>
                        <div className="max-h-64 space-y-3 overflow-y-auto text-xs">
                          {msg.results.map((res, index) => (
                            <div key={res.id || index} className="rounded-md border bg-slate-50 p-2 text-slate-700">
                              <p className="break-all font-mono">
                                <strong>Path:</strong> {res.original_path}
                              </p>
                              <div className="mt-1 flex gap-4">
                                <span className="font-medium">
                                  <strong>Type:</strong> <Badge variant="secondary">{res.media_type}</Badge>
                                </span>
                                <span className="font-medium">
                                  <strong>Score:</strong>{" "}
                                  <Badge variant="outline">{res.combined_score.toFixed(2)}</Badge>
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div className="border-t p-4">
                <div className="flex gap-2">
                  <Input
                    placeholder="Ask about your forensic data..."
                    value={chatInput}
                    onChange={e => setChatInput(e.target.value)}
                    onKeyPress={e => e.key === "Enter" && !isSending && handleSendMessage()}
                    disabled={isSending}
                    className="flex-1"
                  />
                  <Button
                    onClick={handleSendMessage}
                    disabled={isSending}
                    className="bg-slate-900 hover:bg-slate-700"
                  >
                    <Send className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-medium text-slate-900">Quick Questions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {predefinedQuestions.map((question, index) => (
                <button
                  key={index}
                  onClick={() => !isSending && setChatInput(question)}
                  className="w-full rounded-lg bg-gradient-to-r from-purple-50 to-purple-100 p-3 text-left text-sm hover:from-purple-100 hover:to-purple-200"
                >
                  {question}
                </button>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-medium text-slate-900">Current Case Stats</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-600">Total Messages</span>
                <Badge variant="secondary">2,847</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-600">Deleted Items</span>
                <Badge variant="secondary">156</Badge>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}