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
        <h2 className="mb-2 text-4xl font-light tracking-tight text-foreground">AI Assistant</h2>
        <p className="text-lg font-light text-muted-foreground">
          Ask questions about your forensic data in natural language
        </p>
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card className="flex h-[600px] flex-col">
            <CardHeader className="border-b bg-card">
              <CardTitle className="flex items-center gap-2 font-medium text-foreground">
                <Bot className="h-5 w-5 text-signal" />
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
                            ? "bg-primary text-primary-foreground"
                            : "bg-surface-1 border text-foreground"
                        }`}
                      >
                        {msg.isLoading ? (
                          <div className="flex items-center space-x-1 py-1">
                            <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]"></span>
                            <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]"></span>
                            <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground"></span>
                          </div>
                        ) : (
                          <>
                            <p className="whitespace-pre-line text-sm leading-relaxed">{msg.message}</p>
                            {msg.type === "assistant" && msg.result_count && msg.result_count > 0 && (
                              <Button
                                variant="outline"
                                size="sm"
                                className="mt-3 flex items-center gap-2"
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
                        <h4 className="mb-2 flex items-center gap-2 text-base font-semibold text-foreground">
                          <Database className="h-4 w-4 text-muted-foreground" /> Detailed Evidence
                        </h4>
                        <div className="max-h-64 space-y-3 overflow-y-auto text-xs">
                          {msg.results.map((res, index) => (
                            <div key={res.id || index} className="rounded-md border bg-surface-1 p-2 text-foreground">
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
                    variant="signal"
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
              <CardTitle className="text-lg font-medium text-foreground">Quick Questions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {predefinedQuestions.map((question, index) => (
                <button
                  key={index}
                  onClick={() => !isSending && setChatInput(question)}
                  className="w-full rounded-lg bg-surface-1 border p-3 text-left text-sm hover:bg-surface-3"
                >
                  {question}
                </button>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-medium text-foreground">Current Case Stats</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Total Messages</span>
                <Badge variant="secondary">2,847</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Deleted Items</span>
                <Badge variant="high">156</Badge>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}