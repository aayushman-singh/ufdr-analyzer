"use client"
import { useState } from "react"
import { FileUpload } from "@/components/ui/file-upload"
import { FileTree } from "@/components/ui/file-tree"
import { HierarchicalTree } from "@/components/ui/heirarchial-tree"
import { Shield, ArrowLeft, Database, Network, Clock, Maximize2,
  Minimize2, Hash, FileText, HardDrive, Settings } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import Header from "@/components/header"

const ufdrStructure = [
  {
    id: "case-info",
    name: "Case Information",
    type: "folder" as const,
    icon: <FileText className="w-4 h-4 text-purple-500" />,
    children: [
      { id: "case-details", name: "Case-004-Details.xml", type: "file" as const, size: "2.4 KB" },
      { id: "investigator", name: "Investigator-Profile.json", type: "file" as const, size: "1.2 KB" },
      { id: "evidence-chain", name: "Chain-of-Custody.pdf", type: "file" as const, size: "156 KB" },
    ],
  },
  {
    id: "evidence",
    name: "Evidence Items",
    type: "folder" as const,
    icon: <Database className="w-4 h-4 text-blue-500" />,
    count: 3,
    children: [
      {
        id: "disk-image",
        name: "Disk Images",
        type: "folder" as const,
        children: [
          { id: "system-drive", name: "SystemDrive-C.dd", type: "file" as const, size: "250 GB" },
          { id: "data-drive", name: "DataDrive-D.dd", type: "file" as const, size: "500 GB" },
        ],
      },
      {
        id: "memory-dump",
        name: "Memory Dumps",
        type: "folder" as const,
        children: [{ id: "ram-dump", name: "RAM-Dump-001.mem", type: "file" as const, size: "8 GB" }],
      },
      {
        id: "mobile-data",
        name: "Mobile Extractions",
        type: "folder" as const,
        children: [
          { id: "iphone-backup", name: "iPhone-Backup.tar", type: "file" as const, size: "32 GB" },
          {
            id: "device-info",
            name: "Device Info",
            type: "folder" as const,
            children: [
              { id: "whatsapp-data", name: "WhatsApp Data", type: "file" as const, size: "2.1 GB" },
              { id: "whatsapp-media", name: "WhatsApp Media", type: "file" as const, size: "5.4 GB" },
            ],
          },
          {
            id: "sms-data",
            name: "SMS",
            type: "folder" as const,
            children: [
              { id: "ops-system", name: "Operating System SMS", type: "file" as const, size: "45 MB" },
              { id: "media-files", name: "Media Files", type: "file" as const, size: "1.2 GB" },
            ],
          },
          {
            id: "call-history",
            name: "Call History",
            type: "folder" as const,
            children: [
              { id: "call-logs", name: "Call Logs", type: "file" as const, size: "12 MB" },
              { id: "sms-logs", name: "SMS Logs", type: "file" as const, size: "8 MB" },
            ],
          },
        ],
      },
    ],
  },
  {
    id: "filesystem",
    name: "File System Analysis",
    type: "folder" as const,
    icon: <HardDrive className="w-4 h-4 text-green-500" />,
    count: 1247892,
    children: [
      { id: "deleted-files", name: "Deleted Files", type: "folder" as const, count: 15847 },
      { id: "system-files", name: "System Files", type: "folder" as const, count: 89234 },
      { id: "user-files", name: "User Files", type: "folder" as const, count: 1142811 },
    ],
  },
  {
    id: "registry",
    name: "Registry Analysis",
    type: "folder" as const,
    icon: <Settings className="w-4 h-4 text-orange-500" />,
    children: [
      { id: "system-hive", name: "SYSTEM.hiv", type: "file" as const, size: "12.5 MB" },
      { id: "software-hive", name: "SOFTWARE.hiv", type: "file" as const, size: "45.2 MB" },
      { id: "user-hive", name: "NTUSER.DAT", type: "file" as const, size: "8.7 MB" },
    ],
  },
  {
    id: "network",
    name: "Network Analysis",
    type: "folder" as const,
    icon: <Network className="w-4 h-4 text-cyan-500" />,
    children: [
      { id: "connections", name: "Network-Connections.log", type: "file" as const, size: "2.1 MB" },
      { id: "dns-cache", name: "DNS-Cache.txt", type: "file" as const, size: "456 KB" },
      { id: "browser-history", name: "Browser-History.db", type: "file" as const, size: "15.8 MB" },
    ],
  },
  {
    id: "timeline",
    name: "Timeline Data",
    type: "folder" as const,
    icon: <Clock className="w-4 h-4 text-indigo-500" />,
    count: 89234,
    children: [
      { id: "file-activity", name: "File-Activity-Timeline.csv", type: "file" as const, size: "125 MB" },
      { id: "system-events", name: "System-Events-Timeline.json", type: "file" as const, size: "67 MB" },
      { id: "user-activity", name: "User-Activity-Timeline.xml", type: "file" as const, size: "89 MB" },
    ],
  },
  {
    id: "hashes",
    name: "Hash Analysis",
    type: "folder" as const,
    icon: <Hash className="w-4 h-4 text-red-500" />,
    children: [
      { id: "md5-hashes", name: "MD5-Hashes.txt", type: "file" as const, size: "45 MB" },
      { id: "sha256-hashes", name: "SHA256-Hashes.txt", type: "file" as const, size: "89 MB" },
      { id: "known-bad", name: "Known-Bad-Files.db", type: "file" as const, size: "234 KB" },
    ],
  },
  {
    id: "reports",
    name: "Generated Reports",
    type: "folder" as const,
    icon: <FileText className="w-4 h-4 text-purple-500" />,
    children: [
      { id: "executive-summary", name: "Executive-Summary.pdf", type: "file" as const, size: "2.1 MB" },
      { id: "technical-report", name: "Technical-Analysis.html", type: "file" as const, size: "15.6 MB" },
      { id: "findings", name: "Key-Findings.docx", type: "file" as const, size: "4.2 MB" },
    ],
  },
]

export default function UploadPage() {
  const [files, setFiles] = useState<File[]>([])
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [showStructure, setShowStructure] = useState(false)
  const [maximizeHierarchical, setMaximizeHierarchical] = useState(false)
  const router = useRouter()

  const handleFileUpload = (uploadedFiles: File[]) => {
    setFiles(uploadedFiles)
    console.log("Files uploaded:", uploadedFiles)
  }

  const handleStartAnalysis = () => {
    if (files.length === 0) {
      alert("Please upload a UFDR file first.")
      return
    }

    setIsAnalyzing(true)
    setTimeout(() => {
      setIsAnalyzing(false)
      setShowStructure(true)
    }, 3000)
  }

  const handleProceedToDashboard = () => {
    router.push("/dashboard")
  }

return (
    <div className="min-h-screen w-full relative bg-white">
      {/* Purple Glow Top */}
      <div
        className="absolute inset-0 z-0"
        style={{
          background: "#ffffff",
          backgroundImage: `
            radial-gradient(
              circle at top center,
              rgba(173, 109, 244, 0.5),
              transparent 70%
            )
          `,
          filter: "blur(80px)",
          backgroundRepeat: "no-repeat",
        }}
      />

      {/* Actual Content */}
      <div className="relative z-10">
        <Header />

        <main className="max-w-7xl mx-auto px-8 py-16">
          {!showStructure ? (
            <>
              <div className="text-center mb-12">
                <h1 className="text-4xl font-light text-gray-900 mb-4">
                  Upload New UFDR Report
                </h1>
                <p className="text-lg text-gray-600 font-light">
                  Upload your forensic data file to begin AI-powered analysis
                </p>
              </div>

              <div className="mb-12">
                <FileUpload
                  onChange={handleFileUpload}
                  accept=".ufdr"
                  maxSize={500}
                  className="max-w-3xl mx-auto"
                />
              </div>

              {files.length > 0 && (
                <div className="text-center">
                  <button
                    onClick={handleStartAnalysis}
                    disabled={isAnalyzing}
                    className="bg-slate-900 text-white font-medium py-3 px-8 rounded-lg hover:bg-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isAnalyzing ? "Starting Analysis..." : "Start Analysis"}
                  </button>
                </div>
              )}

              {isAnalyzing && (
                <div className="mt-8 text-center">
                  <div className="inline-flex items-center space-x-2 text-purple-600">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-purple-600"></div>
                    <span>Processing your UFDR file...</span>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div>
              <div className="text-center mb-8">
                <div className="inline-flex items-center space-x-2 text-green-600 mb-4">
                  <div className="w-5 h-5 bg-green-100 rounded-full flex items-center justify-center">
                    <div className="w-2 h-2 bg-green-600 rounded-full"></div>
                  </div>
                  <span className="font-medium">Analysis Complete</span>
                </div>
                <h1 className="text-3xl font-light text-gray-900 mb-2">
                  UFDR File Structure
                </h1>
                <p className="text-lg text-gray-600 font-light">
                  Your forensic data has been processed and indexed. Explore the structure below.
                </p>
              </div>

              <div
                className={`grid gap-8 mb-8 ${
                  maximizeHierarchical ? "grid-cols-1" : "lg:grid-cols-2"
                }`}
              >
                {/* File Tree Structure */}
                {!maximizeHierarchical && (
                  <div className="bg-gray-50 rounded-xl p-6">
                    <h3 className="text-xl font-semibold text-gray-900 mb-4 text-center">
                      Detailed File Structure
                    </h3>
                    <FileTree data={ufdrStructure} className="max-w-full" />
                  </div>
                )}
{/* Full-screen Hierarchical Tree when maximized */}
{maximizeHierarchical && (
  <div className="fixed inset-0 bg-white z-50 flex flex-col">
    <div className="flex justify-between items-center p-4 border-b">
      <h3 className="text-xl font-semibold text-gray-900">Hierarchical Overview</h3>
      <button
        onClick={() => setMaximizeHierarchical(false)}
        className="text-gray-500 hover:text-gray-700"
      >
        <Minimize2 className="w-5 h-5" />
      </button>
    </div>
    <div className="flex-1 overflow-auto p-4">
      <HierarchicalTree data={ufdrStructure} className="w-full h-full" />
    </div>
  </div>
)}

                {/* Hierarchical Tree Structure */}
              <div className="bg-gray-50 rounded-xl p-6 relative">
  <div className="flex justify-between items-center mb-4">
    <h3 className="text-xl font-semibold text-gray-900 text-center flex-1">
      Hierarchical Overview
    </h3>
    <button
      onClick={() => setMaximizeHierarchical(true)}
      className="text-gray-500 hover:text-gray-700"
    >
      <Maximize2 className="w-5 h-5" />
    </button>
  </div>
  <HierarchicalTree data={ufdrStructure} className="max-w-full" />
</div>

              </div>

              <div className="text-center space-x-4">
                <button
                  onClick={handleProceedToDashboard}
                  className="bg-black text-white font-medium py-3 px-8 rounded-lg hover:bg-purple-700 transition-colors"
                >
                  Start Investigation
                </button>
                <button
                  onClick={() => setShowStructure(false)}
                  className="bg-gray-100 text-gray-700 font-medium py-3 px-8 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  Upload Another File
                </button>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
