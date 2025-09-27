import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Bot, User, Send } from "lucide-react"
import { ChatMessage, predefinedQuestions } from "../data"

interface AiAssistantViewProps {
  chatMessages: ChatMessage[]
  chatInput: string
  setChatInput: (value: string) => void
  handleSendMessage: () => void
}

export function AiAssistantView({
  chatMessages,
  chatInput,
  setChatInput,
  handleSendMessage,
}: AiAssistantViewProps) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-4xl font-light text-slate-900 tracking-tight mb-2">AI Assistant</h2>
        <p className="text-lg text-slate-600 font-light">
          Ask questions about your forensic data in natural language
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
           <Card className="h-[600px] flex flex-col">
  <CardHeader className="border-b bg-gradient-to-r from-purple-50 to-purple-100">
    <CardTitle className="flex items-center gap-2 text-slate-900 font-medium">
      <Bot className="w-5 h-5 text-purple-600" />
      Forensic AI Chat
    </CardTitle>
  </CardHeader>

  {/* CardContent as full flex column */}
  <CardContent className="flex-1 flex flex-col p-0 overflow-hidden">
    {/* scroll area forced to available space */}
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {chatMessages.map((msg) => (
        <div
          key={msg.id}
          className={`flex ${
            msg.type === "user" ? "justify-end" : "justify-start"
          }`}
        >
          <div
            className={`max-w-full md:max-w-[80%] break-words rounded-2xl px-4 py-3 ${
              msg.type === "user"
                ? "bg-slate-900 text-white"
                : "bg-gradient-to-br from-purple-50 to-purple-100 text-slate-900"
            }`}
          >
            <p className="text-sm leading-relaxed whitespace-pre-line">
              {msg.message}
            </p>
          </div>
        </div>
      ))}
    </div>

    <div className="border-t p-4">
      <div className="flex gap-2">
        <Input
          placeholder="Ask about your forensic data..."
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          onKeyPress={(e) => e.key === "Enter" && handleSendMessage()}
          className="flex-1"
        />
        <Button
          onClick={handleSendMessage}
          className="bg-slate-900 hover:bg-slate-700"
        >
          <Send className="w-4 h-4" />
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
                            onClick={() => setChatInput(question)}
                            className="w-full text-left p-3 text-sm bg-gradient-to-r from-purple-50 to-purple-100 hover:from-purple-100 hover:to-purple-200 rounded-lg"
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
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-slate-600">Total Messages</span>
                      <Badge variant="secondary">2,847</Badge>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-slate-600">Deleted Items</span>
                      <Badge variant="secondary">156</Badge>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-slate-600">Contacts</span>
                      <Badge variant="secondary">89</Badge>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-slate-600">Media Files</span>
                      <Badge variant="secondary">423</Badge>
                    </div>
                  </CardContent>
                </Card>
        </div>
      </div>
    </div>
  )
}