import { Bot, Search, Clock, BarChart3, Network, LucideIcon, MapPin, Phone, MessageCircle, Activity, GitBranch } from "lucide-react"

// Type Definitions
export interface MenuItem {
  title: string
  icon: LucideIcon
  description: string
  badge?: string
  content: string
}

export interface ChatEvidenceResult {
  id?: string | number;
  original_path: string;
  media_type: string;
  combined_score: number;
}

export interface ChatMessage {
  id: number;
  type: "user" | "assistant";
  message: string;
  timestamp: string;
  isLoading?: boolean;      
  results?: ChatEvidenceResult[];          
  result_count?: number;    
}

export interface TimelineEvent {
    time: string
    date: string
    event: string
    type: string
    icon: LucideIcon
}


// Data Exports
export const menuItems: MenuItem[] = [
  { title: "AI Assistant", icon: Bot, description: "Natural language interface for querying evidence", badge: "New", content: "ai-assistant" },
  { title: "Evidence Search", icon: Search, description: "AI-powered search across all forensic data", content: "evidence-search" },
  { title: "Timeline Analysis", icon: Clock, description: "Chronological view of events and activities", content: "timeline-analysis" },
  { title: "Reports & Analytics", icon: BarChart3, description: "Generate reports, visualizations, and summaries", content: "reports-analytics" },
  { title: "Data Visualization", icon: Network, description: "Charts, graphs, network diagrams for evidence", content: "data-visualization" },
  { title: "Graph Analysis", icon: GitBranch, description: "Network analysis and relationship mapping", badge: "New", content: "graph-analysis" },
];

export const mockChatMessages: ChatMessage[] = [
  // { id: 1, type: "user", message: "Show me all deleted WhatsApp messages from last week", timestamp: "10:30 AM" },

{ id: 1, type: "assistant", message: "Welcome to your AI Forensic Assistant. I am connected to the case data and ready to help you with your investigation. Here's what I can do:\n\n• **Search for Evidence:** Find specific files, messages, or browser history.\n• **Analyze Timelines:** Reconstruct a sequence of events from digital footprints.\n• **Summarize Communications:** Condense conversations or logs into key points.\n• **Identify Connections:** Uncover relationships between contacts, files, and events.\n\nTo get started, simply ask me a question about the data, like 'Were there any images downloaded on October 5th, 2025?'", timestamp: "10:50 PM" } // { id: 3, type: "user", message: "Find connections between John Doe and suspicious contacts", timestamp: "10:35 AM" },
  // { id: 4, type: "assistant", message: "Analysis complete! I found several connections between John Doe and flagged contacts:\n\n🔗 **Direct Connections:**\n• 47 calls with 'Mike Johnson' (flagged for fraud)\n• 12 WhatsApp conversations with 'Alex Rivera' (money laundering suspect)\n\n📍 **Location Overlaps:**\n• Both visited 123 Oak Street on March 10th\n• Simultaneous presence at Central Bank on March 15th\n\n💰 **Financial Patterns:**\n• $2,500 transfer mentioned in messages\n• Coordinated ATM withdrawals within 30 minutes", timestamp: "10:36 AM" },
];

export const predefinedQuestions: string[] = [
  "Show me all deleted messages from this week",
  "Find suspicious financial transactions",
  "What locations was the device at during March 15-20?",
  "Analyze call patterns for unusual activity",
  "Show me all contacts with criminal records",
  "Find messages mentioning drugs or weapons",
];

export const mockTimelineData: TimelineEvent[] = [
    { time: "09:15 AM", date: "Mar 15", event: "Device location: Home address", type: "location", icon: MapPin },
    { time: "10:30 AM", date: "Mar 15", event: "WhatsApp message to Mike Johnson", type: "message", icon: MessageCircle },
    { time: "11:45 AM", date: "Mar 15", event: "Phone call from Sarah Wilson (12 min)", type: "call", icon: Phone },
    { time: "02:15 PM", date: "Mar 15", event: "Location change: Central Bank", type: "location", icon: MapPin },
    { time: "02:30 PM", date: "Mar 15", event: "Deleted WhatsApp conversation", type: "deleted", icon: MessageCircle },
    { time: "03:45 PM", date: "Mar 15", event: "ATM withdrawal: $500", type: "financial", icon: Activity },
];