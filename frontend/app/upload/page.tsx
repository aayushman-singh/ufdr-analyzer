"use client"
import { useState, useEffect, useCallback } from "react"
import { FileTree } from "@/components/ui/file-tree"
import { HierarchicalTree } from "@/components/ui/heirarchial-tree"
import { BackendDataDisplay } from "@/components/ui/backend-data-display"
import { Button } from "@/components/ui/button"
import { Database, Maximize2, Minimize2, FileText, HardDrive, Network, Clock, Hash, Settings } from "lucide-react"
import { useRouter } from "next/navigation"
import Header from "@/components/header"

// Types for backend data
interface BackendData {
  status: string;
  filename: string;
  file_path: string;
  processing_time: string;
  ingest_result?: {
    messages?: Array<{content?: string; [key: string]: unknown}>;
    contacts?: Array<{name?: string; [key: string]: unknown}>;
    calls?: Array<{duration?: string; [key: string]: unknown}>;
    media?: Array<{[key: string]: unknown}>;
    total_files?: number;
  };
  aleapp_processed?: boolean;
  aleapp_report_path?: string;
  aleapp_web_url?: string;
}

// Function to extract file structure from ALEAPP report
const extractAleappFileStructure = async (backendData: BackendData | null) => {
  if (!backendData?.aleapp_report_path) {
    return null;
  }

  try {
    // Fetch the ALEAPP report directory structure
    const response = await fetch(`http://localhost:8000/ingest/aleapp-structure?report_path=${encodeURIComponent(backendData.aleapp_report_path)}`);
    if (!response.ok) {
      console.warn('Failed to fetch ALEAPP structure');
      return null;
    }
    
    const structure = await response.json();
    return structure;
  } catch (error) {
    console.warn('Error fetching ALEAPP structure:', error);
    return null;
  }
};

// Types for ALEAPP structure
interface AleappFile {
  name: string;
  path: string;
  size: number;
  size_formatted: string;
  extension: string;
}

interface AleappStructure {
  root: string;
  directories: Array<{name: string; path: string; size: number}>;
  files: AleappFile[];
  total_files: number;
  total_dirs: number;
  categories: {
    html_reports: AleappFile[];
    tsv_exports: AleappFile[];
    databases: AleappFile[];
    timeline: AleappFile[];
    data_extraction: AleappFile[];
    scripts: AleappFile[];
    other: AleappFile[];
  };
}

// Function to transform ALEAPP structure into tree format
const transformAleappToTree = (aleappData: AleappStructure | null) => {
  if (!aleappData) {
    return ufdrStructure; // Fallback to original structure
  }

  const { categories } = aleappData;
  
  // Create array of category definitions
  const categoryDefinitions = [
    {
      id: "aleapp-reports",
      name: "ALEAPP Analysis Reports",
      icon: <FileText className="w-4 h-4 text-signal" />,
      data: categories.html_reports,
      limit: 10
    },
    {
      id: "aleapp-exports", 
      name: "TSV Exports",
      icon: <Database className="w-4 h-4 text-info" />,
      data: categories.tsv_exports,
      limit: 10
    },
    {
      id: "aleapp-databases",
      name: "Analysis Databases", 
      icon: <HardDrive className="w-4 h-4 text-signal" />,
      data: categories.databases,
      limit: null
    },
    {
      id: "aleapp-timeline",
      name: "Timeline Data",
      icon: <Clock className="w-4 h-4 text-muted-foreground" />,
      data: categories.timeline,
      limit: null
    },
    {
      id: "aleapp-data",
      name: "Extracted Data",
      icon: <Settings className="w-4 h-4 text-muted-foreground" />,
      data: categories.data_extraction,
      limit: 10
    },
    {
      id: "aleapp-scripts",
      name: "Script Logs",
      icon: <Network className="w-4 h-4 text-info" />,
      data: categories.scripts,
      limit: null
    }
  ];

  // Filter out categories with no data and transform the rest
  return categoryDefinitions
    .filter(category => category.data && category.data.length > 0)
    .map(category => ({
      id: category.id,
      name: category.name,
      type: "folder" as const,
      icon: category.icon,
      count: category.data!.length,
      children: (category.limit ? category.data!.slice(0, category.limit) : category.data!)
        .map((file: AleappFile, index: number) => ({
          id: `${category.id}-${index}`,
          name: file.name,
          type: "file" as const,
          size: file.size_formatted
        }))
    }));
};

// Original hardcoded UFDR structure
const ufdrStructure = [
  {
    id: "case-info",
    name: "Case Information",
    type: "folder" as const,
    icon: <FileText className="w-4 h-4 text-signal" />,
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
    icon: <Database className="w-4 h-4 text-info" />,
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
    icon: <HardDrive className="w-4 h-4 text-signal" />,
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
    icon: <Settings className="w-4 h-4 text-muted-foreground" />,
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
    icon: <Network className="w-4 h-4 text-info" />,
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
    icon: <Clock className="w-4 h-4 text-muted-foreground" />,
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
    icon: <Hash className="w-4 h-4 text-[var(--severity-high)]" />,
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
    icon: <FileText className="w-4 h-4 text-signal" />,
    children: [
      { id: "executive-summary", name: "Executive-Summary.pdf", type: "file" as const, size: "2.1 MB" },
      { id: "technical-report", name: "Technical-Analysis.html", type: "file" as const, size: "15.6 MB" },
      { id: "findings", name: "Key-Findings.docx", type: "file" as const, size: "4.2 MB" },
    ],
  },
];

export default function UploadPage() {
  const [filePath, setFilePath] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [showStructure, setShowStructure] = useState(false);
  const [maximizeHierarchical, setMaximizeHierarchical] = useState(false);
  const [fileInfo, setFileInfo] = useState<{valid: boolean; file_size_gb: number; file_path: string; readable: boolean} | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [backendData, setBackendData] = useState<BackendData | null>(null);
  const [aleappStructure, setAleappStructure] = useState<AleappStructure | null>(null);
  const [isLoadingStructure, setIsLoadingStructure] = useState(false);
  const router = useRouter();

  const validateFilePath = useCallback(async (pathToValidate?: string) => {
    const path = pathToValidate || filePath;
    if (!path.trim()) {
      return;
    }

    setIsValidating(true);
    try {
      const response = await fetch(
        `http://localhost:8000/ingest/validate-path?file_path=${encodeURIComponent(
          path
        )}`
      );
      const data = await response.json();

      if (data.valid) {
        setFileInfo(data);
      } else {
        alert(`Invalid file path: ${data.error}`);
        setFileInfo(null);
      }
    } catch (error) {
      console.error("Validation failed:", error);
      setFileInfo(null);
      // Don't show alert for network errors, just log them
      if (error instanceof TypeError && error.message.includes('fetch')) {
        console.log("Backend server not running - validation skipped");
      } else {
        alert(
          "Failed to validate file path. Please check the server connection."
        );
      }
    } finally {
      setIsValidating(false);
    }
  }, [filePath]);

  // Auto-validate file path when it changes
  useEffect(() => {
    if (filePath.trim()) {
      const timeoutId = setTimeout(() => {
        validateFilePath();
      }, 1000);
      return () => clearTimeout(timeoutId);
    }
  }, [filePath, validateFilePath]);

  const handleFilePathChange = (path: string) => {
    setFilePath(path);
    setFileInfo(null);
  };

  const handleSelectFile = async () => {
    if (window.electronAPI) {
      const selectedPath = await window.electronAPI.selectFile();
      if (selectedPath) {
        setFilePath(selectedPath);
        setFileInfo(null);
        // Automatically validate the selected file
        await validateFilePath(selectedPath);
      }
    } else {
      alert("File selection is only available in the Electron app");
    }
  };

  const handleStartAnalysis = async () => {
    if (!filePath.trim()) {
      alert("Please enter a file path first.");
      return;
    }

    // If validation failed due to network issues, allow proceeding anyway
    if (fileInfo && !fileInfo.valid) {
      alert("Please fix the file path before proceeding.");
      return;
    }

    setIsAnalyzing(true);
    try {
      const response = await fetch("http://localhost:8000/ingest/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          file_path: filePath,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Processing failed");
      }

      const result = await response.json();
      console.log("Processing result:", result);

      // Store backend data
      setBackendData(result);

      // Store run_id in localStorage for chat system
      if (result.run_id) {
        localStorage.setItem("run_id", result.run_id);
        console.log("Stored run_id in localStorage:", result.run_id);
      }

      // Load ALEAPP structure if available
      if (result.aleapp_processed && result.aleapp_report_path) {
        console.log('Loading ALEAPP structure for:', result.aleapp_report_path);
        setIsLoadingStructure(true);
        try {
          const aleappStructure = await extractAleappFileStructure(result);
          console.log('ALEAPP structure loaded:', aleappStructure);
          setAleappStructure(aleappStructure);
        } catch (error) {
          console.warn('Failed to load ALEAPP structure:', error);
        } finally {
          setIsLoadingStructure(false);
        }
      } else {
        console.log('No ALEAPP processing or report path available');
      }

      // Show success and proceed to structure view
      setShowStructure(true);
    } catch (error: unknown) {
      console.error("Processing failed:", error);
      const errorMessage = error instanceof Error ? error.message : "Unknown error occurred";
      alert(`Processing failed: ${errorMessage}`);
    } finally {
      setIsAnalyzing(false);
    }
  };


  const handleProceedToDashboard = () => {
    router.push("/dashboard");
  };

  return (
    <div className="min-h-screen w-full relative bg-background">
      {/* Signal Glow Top */}
      <div
        className="fixed inset-0 z-0"
        style={{
          background: "var(--background)",
          backgroundImage: `
            radial-gradient(
              circle at top center,
              color-mix(in oklch, var(--signal) 14%, transparent),
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
                <h1 className="text-4xl font-light text-foreground mb-4">
                  Process UFDR File
                </h1>
                <p className="text-lg text-muted-foreground font-light">
                  Enter the server file path to begin AI-powered analysis
                </p>
              </div>

              <div className="mb-12 max-w-3xl mx-auto">
                <div className="bg-card rounded-xl border border-border p-6">
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-foreground mb-2">
                        Server File Path
                      </label>
                      <div className="flex space-x-2">
                        <input
                          type="text"
                          value={filePath}
                          onChange={(e) => handleFilePathChange(e.target.value)}
                          placeholder="/data/ufdr/case-001.ufdr"
                          className="flex-1 px-4 py-3 border border-border bg-background text-foreground rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
                        />
                        <Button
                          variant="outline"
                          onClick={handleSelectFile}
                          className="px-4 py-3"
                        >
                          Browse
                        </Button>
                      </div>
                      <p className="text-sm text-muted-foreground mt-1">
                        Enter the full path to your UFDR file on the server (validation happens automatically)
                      </p>
                    </div>

                    {isValidating && (
                      <div className="bg-info/10 border border-info/30 rounded-lg p-4">
                        <div className="flex items-center space-x-2 text-info">
                          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-info"></div>
                          <span className="font-medium">Validating file path...</span>
                        </div>
                      </div>
                    )}

                    {fileInfo && (
                      <div className="bg-signal/10 border border-signal/30 rounded-lg p-4">
                        <div className="flex items-center space-x-2 text-signal mb-2">
                          <div className="w-2 h-2 bg-signal rounded-full"></div>
                          <span className="font-medium">File Validated</span>
                        </div>
                        <div className="text-sm text-signal space-y-1">
                          <div>File Size: {fileInfo.file_size_gb} GB</div>
                          <div>Path: {fileInfo.file_path}</div>
                          <div>
                            Readable: {fileInfo.readable ? "Yes" : "No"}
                          </div>
                        </div>
                      </div>
                    )}

                    <div className="flex justify-center">
                      <Button
                        variant="signal"
                        size="lg"
                        onClick={handleStartAnalysis}
                        disabled={isAnalyzing || (fileInfo?.valid === false)}
                      >
                        {isAnalyzing ? "Processing..." : "Start Analysis"}
                      </Button>
                    </div>
                  </div>
                </div>
              </div>

              {isAnalyzing && (
                <div className="mt-8 text-center">
                  <div className="inline-flex items-center space-x-2 text-signal">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-signal"></div>
                    <span>
                      Processing large UFDR file... This may take several
                      minutes.
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-2">
                    Large files (30-150GB) require significant processing time
                  </p>
                </div>
              )}
            </>
          ) : (
            <div>
              <div className="text-center mb-8">
                <div className="inline-flex items-center space-x-2 text-signal mb-4">
                  <div className="w-5 h-5 bg-signal/20 rounded-full flex items-center justify-center">
                    <div className="w-2 h-2 bg-signal rounded-full"></div>
                  </div>
                  <span className="font-medium">Analysis Complete</span>
                </div>
                <h1 className="text-3xl font-light text-foreground mb-2">
                  UFDR File Structure
                </h1>
                <p className="text-lg text-muted-foreground font-light">
                  Your forensic data has been processed and indexed. Explore the
                  structure below.
                </p>
                {backendData && (
                  <div className="text-sm text-muted-foreground mt-2">
                    Processed {backendData.filename} in {backendData.processing_time}
                  </div>
                )}
              </div>

              {/* Backend Data Display */}
              {backendData && (
                <div className="mb-8">
                  <BackendDataDisplay data={backendData} />
                  
                  {/* Debug: Manual ALEAPP structure loading */}
                  {backendData.aleapp_processed && backendData.aleapp_report_path && !aleappStructure && (
                    <div className="mt-4 p-4 bg-[var(--severity-medium)]/10 border border-[var(--severity-medium)]/30 rounded-lg">
                      <p className="text-sm text-[var(--severity-medium)] mb-2">
                        ALEAPP structure not loaded. Click to load manually:
                      </p>
                      <button
                        onClick={async () => {
                          console.log('Manually loading ALEAPP structure...');
                          setIsLoadingStructure(true);
                          try {
                            const structure = await extractAleappFileStructure(backendData);
                            console.log('Manual load result:', structure);
                            setAleappStructure(structure);
                          } catch (error) {
                            console.error('Manual load failed:', error);
                          } finally {
                            setIsLoadingStructure(false);
                          }
                        }}
                        className="bg-[var(--severity-medium)] text-background px-3 py-1 rounded text-sm hover:brightness-110"
                      >
                        Load ALEAPP Structure
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* File Tree Structure */}
              {!maximizeHierarchical && (
                <div className="bg-surface-1 rounded-xl p-6 mb-8">
                  <h3 className="text-xl font-semibold text-foreground mb-4 text-center">
                    Detailed File Structure
                  </h3>
                  {/* Debug info */}
                  <div className="text-xs text-muted-foreground mb-2 text-center">
                    {aleappStructure ? `Using ALEAPP data (${aleappStructure.total_files} files)` : 'Using hardcoded data'}
                  </div>
                  {isLoadingStructure ? (
                    <div className="flex items-center justify-center py-8">
                      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-signal"></div>
                      <span className="ml-2 text-muted-foreground">Loading ALEAPP structure...</span>
                    </div>
                  ) : (
                    <FileTree
                      data={aleappStructure ? (() => {
                        console.log('Using ALEAPP structure:', aleappStructure);
                        return transformAleappToTree(aleappStructure);
                      })() : (() => {
                        console.log('Using hardcoded structure');
                        return ufdrStructure;
                      })()}
                      className="max-w-full"
                    />
                  )}
                </div>
              )}

              <div className="mb-8">
                {/* Full-screen Hierarchical Tree when maximized */}
                {maximizeHierarchical && (
                  <div className="fixed inset-0 bg-background z-50 flex flex-col">
                    <div className="flex justify-between items-center p-4 border-b border-border">
                      <h3 className="text-xl font-semibold text-foreground">
                        Hierarchical Overview
                      </h3>
                      <button
                        onClick={() => setMaximizeHierarchical(false)}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <Minimize2 className="w-5 h-5" />
                      </button>
                    </div>
                    <div className="flex-1 overflow-auto p-4">
                      <HierarchicalTree
                        data={aleappStructure ? (() => {
                          console.log('Using ALEAPP structure (maximized):', aleappStructure);
                          return transformAleappToTree(aleappStructure);
                        })() : (() => {
                          console.log('Using hardcoded structure (maximized)');
                          return ufdrStructure;
                        })()}
                        className="w-full h-full"
                      />
                    </div>
                  </div>
                )}

                {/* Hierarchical Tree Structure */}
                <div className="bg-surface-1 rounded-xl p-6 relative mb-8">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="text-xl font-semibold text-foreground text-center flex-1">
                      Hierarchical Overview
                    </h3>
                    <button
                      onClick={() => setMaximizeHierarchical(true)}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <Maximize2 className="w-5 h-5" />
                    </button>
                  </div>
                  <HierarchicalTree
                    data={aleappStructure ? (() => {
                      console.log('Using ALEAPP structure (regular):', aleappStructure);
                      return transformAleappToTree(aleappStructure);
                    })() : (() => {
                      console.log('Using hardcoded structure (regular)');
                      return ufdrStructure;
                    })()}
                    className="w-full"
                  />
                </div>

                <div className="text-center space-x-4">
                  <Button
                    variant="signal"
                    size="lg"
                    onClick={handleProceedToDashboard}
                  >
                    Start Investigation
                  </Button>
                  <Button
                    variant="outline"
                    size="lg"
                    onClick={() => setShowStructure(false)}
                  >
                    Upload Another File
                  </Button>
                </div>
              </div>
            </div>
          )}
          </main>
      </div>
    </div>
  );
}