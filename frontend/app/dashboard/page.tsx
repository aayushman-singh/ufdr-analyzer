"use client"
import { useState } from "react"
import {
  Shield,
  ArrowLeft,
  Database,
  Network,
  Clock,
  Hash,
  FileText,
  HardDrive,
  Settings,
  Bot,
  User,
  CornerDownLeft,
  FileTree as FileTreeIcon,
  GitMerge,
  BarChartHorizontal,
  LayoutDashboard,
} from "lucide-react"
import Link from "next/link"
import Header from "@/components/header" // Assuming you have this component

// Mock data for demonstration
const mockTimelineData = [
  { time: "08:15", event: "File Accessed: /user/docs/confidential.docx", type: "file" },
  { time: "08:17", event: "Network Connection: 192.168.1.10 -> 8.8.8.8", type: "network" },
  { time: "09:30", event: "SMS Sent to +1-555-123-4567", type: "message" },
  { time: "10:05", event: "File Deleted: /downloads/archive.zip", type: "file" },
  { time: "11:22", event: "Browser History: visited shady-website.com", type: "network" },
];

export default function DashboardPage() {
  const [messages, setMessages] = useState([
    {
      sender: "ai",
      text: "Welcome, Investigator. I'm ready to assist with your case. How can I help you analyze this UFDR file?",
    },
  ])
  const [input, setInput] = useState("")
  const [activeTab, setActiveTab] = useState("overview")

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim()) return

    const userMessage = { sender: "user", text: input }
    setMessages((prev) => [...prev, userMessage])
    setInput("")

    // Simulate AI response
    setTimeout(() => {
      const aiResponse = {
        sender: "ai",
        text: `Searching for results related to: "${input}"... I've highlighted the relevant findings in the Timeline view.`,
      }
      setMessages((prev) => [...prev, aiResponse])
      setActiveTab("timeline") // Switch tab based on query
    }, 1500)
  }

  // A simple placeholder for the graph view
  const GraphView = () => (
    <div className="p-4 text-center">
      <h3 className="text-lg font-semibold mb-4">Relationship Graph</h3>
      <p className="text-sm text-gray-500">
        Visualizing connections between entities...
      </p>
      {/* This is a simplified SVG to represent a graph */}
      <svg width="100%" height="300" viewBox="0 0 400 300">
          <circle cx="50" cy="150" r="20" fill="#a78bfa" />
          <text x="50" y="155" textAnchor="middle" fill="white" fontSize="10">User A</text>
          <circle cx="200" cy="80" r="20" fill="#a78bfa" />
          <text x="200" y="85" textAnchor="middle" fill="white" fontSize="10">File.zip</text>
          <circle cx="200" cy="220" r="20" fill="#a78bfa" />
          <text x="200" y="225" textAnchor="middle" fill="white" fontSize="10">User B</text>
          <circle cx="350" cy="150" r="20" fill="#a78bfa" />
          <text x="350" y="155" textAnchor="middle" fill="white" fontSize="10">Contact</text>
          <line x1="68" y1="145" x2="182" y2="90" stroke="#d1d5db" />
          <line x1="68" y1="155" x2="182" y2="210" stroke="#d1d5db" />
          <line x1="218" y1="90" x2="332" y2="145" stroke="#d1d5db" />
      </svg>
    </div>
  );

  return (
    <div className="min-h-screen w-full relative bg-white">
      {/* Background Glow */}
      <div
        className="fixed inset-x-0 top-0 z-0 h-[500px]"
        style={{
          background: "radial-gradient(circle at top center, rgba(173, 109, 244, 0.4), transparent 70%)",
          filter: "blur(100px)",
        }}
      />

      {/* Actual Content */}
      <div className="relative z-10 flex flex-col h-screen">
        <Header />

        <main className="flex-1 grid lg:grid-cols-2 gap-8 max-w-[90rem] mx-auto px-8 py-8 w-full">
          {/* Left Panel: Investigation Workspace */}
          <div className="bg-gray-50/80 backdrop-blur-sm rounded-xl border border-gray-200 flex flex-col">
            <div className="p-4 border-b border-gray-200">
              <nav className="flex space-x-2">
                <button onClick={() => setActiveTab("overview")} className={`flex items-center space-x-2 px-3 py-1.5 text-sm font-medium rounded-md ${activeTab === 'overview' ? 'bg-white shadow-sm text-gray-800' : 'text-gray-500 hover:bg-gray-200'}`}>
                  <LayoutDashboard size={16} /> <span>Overview</span>
                </button>
                <button onClick={() => setActiveTab("timeline")} className={`flex items-center space-x-2 px-3 py-1.5 text-sm font-medium rounded-md ${activeTab === 'timeline' ? 'bg-white shadow-sm text-gray-800' : 'text-gray-500 hover:bg-gray-200'}`}>
                  <BarChartHorizontal size={16} /> <span>Timeline</span>
                </button>
                <button onClick={() => setActiveTab("graph")} className={`flex items-center space-x-2 px-3 py-1.5 text-sm font-medium rounded-md ${activeTab === 'graph' ? 'bg-white shadow-sm text-gray-800' : 'text-gray-500 hover:bg-gray-200'}`}>
                  <GitMerge size={16} /> <span>Graph</span>
                </button>
              </nav>
            </div>
            <div className="flex-1 p-6 overflow-y-auto">
              {activeTab === "overview" && (<div><h3 className="text-xl font-semibold mb-4">Case Overview</h3> <p className="text-gray-600">Key metrics and findings will be displayed here.</p></div>)}
              {activeTab === "timeline" && (
                <div>
                  <h3 className="text-xl font-semibold mb-4">Event Timeline</h3>
                  <ul className="space-y-4">
                    {mockTimelineData.map((item, index) => (
                      <li key={index} className="flex items-start space-x-3">
                        <div className="flex-shrink-0 pt-1">
                          {item.type === 'file' && <FileText className="w-4 h-4 text-purple-500" />}
                          {item.type === 'network' && <Network className="w-4 h-4 text-cyan-500" />}
                          {item.type === 'message' && <User className="w-4 h-4 text-blue-500" />}
                        </div>
                        <div className="flex-1">
                          <p className="text-sm text-gray-800">{item.event}</p>
                          <p className="text-xs text-gray-500">{item.time}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {activeTab === "graph" && <GraphView />}
            </div>
          </div>

          {/* Right Panel: AI Chatbot */}
          <div className="bg-gray-50/80 backdrop-blur-sm rounded-xl border border-gray-200 flex flex-col h-full">
            <div className="p-4 border-b border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900 flex items-center">
                <Bot className="w-5 h-5 mr-2 text-purple-600" />
                AI Forensic Assistant
              </h3>
            </div>
            <div className="flex-1 p-6 space-y-6 overflow-y-auto">
              {messages.map((msg, index) => (
                <div key={index} className={`flex items-start gap-3 ${msg.sender === 'user' ? 'justify-end' : ''}`}>
                  {msg.sender === 'ai' && (
                    <div className="w-8 h-8 rounded-full bg-purple-100 flex items-center justify-center flex-shrink-0">
                      <Bot className="w-5 h-5 text-purple-600" />
                    </div>
                  )}
                  <div className={`p-3 rounded-lg max-w-sm ${msg.sender === 'user' ? 'bg-black text-white' : 'bg-white'}`}>
                    <p className="text-sm">{msg.text}</p>
                  </div>
                </div>
              ))}
            </div>
            <div className="p-4 border-t border-gray-200">
              <div className="text-center mb-2">
                  <button onClick={() => setInput("Summarize key findings")} className="text-xs bg-gray-200 text-gray-600 px-2 py-1 rounded-md hover:bg-gray-300">Summarize</button>
                  <button onClick={() => setInput("Show all network connections")} className="text-xs bg-gray-200 text-gray-600 px-2 py-1 ml-2 rounded-md hover:bg-gray-300">Network Connections</button>
              </div>
              <form onSubmit={handleSendMessage} className="relative">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Ask a question about the case..."
                  className="w-full pl-4 pr-12 py-2.5 text-sm bg-white border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-400 focus:outline-none"
                />
                <button type="submit" className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-gray-500 hover:text-purple-600 rounded-full">
                  <CornerDownLeft size={18} />
                </button>
              </form>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}