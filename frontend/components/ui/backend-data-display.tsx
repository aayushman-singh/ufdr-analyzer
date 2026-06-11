"use client"

import { Database, FileText, HardDrive, Clock, Hash, Settings, Network, ExternalLink } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

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

interface BackendDataDisplayProps {
  data: BackendData | null;
}

export function BackendDataDisplay({ data }: BackendDataDisplayProps) {
  if (!data) {
    return null;
  }

  const { ingest_result } = data;

  return (
    <div className="space-y-6">
      {/* Processing Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-signal" />
            Processing Summary
          </CardTitle>
          <CardDescription>
            Details about the file processing and analysis
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-muted-foreground">Filename</label>
              <p className="text-sm">{data.filename}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-muted-foreground">Processing Time</label>
              <p className="text-sm">{data.processing_time}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-muted-foreground">Status</label>
              <Badge variant={data.status === "success" ? "default" : "destructive"}>
                {data.status}
              </Badge>
            </div>
            <div>
              <label className="text-sm font-medium text-muted-foreground">ALEAPP Processed</label>
              <Badge variant={data.aleapp_processed ? "default" : "secondary"}>
                {data.aleapp_processed ? "Yes" : "No"}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Data Statistics */}
      {ingest_result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="w-5 h-5 text-info" />
              Data Statistics
            </CardTitle>
            <CardDescription>
              Extracted data counts and analysis results
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center p-4 bg-info/10 rounded-lg">
                <div className="text-2xl font-bold text-info">
                  {ingest_result.messages?.length || 0}
                </div>
                <div className="text-sm text-info">Messages</div>
              </div>
              <div className="text-center p-4 bg-signal/10 rounded-lg">
                <div className="text-2xl font-bold text-signal">
                  {ingest_result.contacts?.length || 0}
                </div>
                <div className="text-sm text-signal">Contacts</div>
              </div>
              <div className="text-center p-4 bg-[var(--severity-medium)]/10 rounded-lg">
                <div className="text-2xl font-bold text-[var(--severity-medium)]">
                  {ingest_result.calls?.length || 0}
                </div>
                <div className="text-sm text-[var(--severity-medium)]">Call Records</div>
              </div>
              <div className="text-center p-4 bg-surface-3 rounded-lg">
                <div className="text-2xl font-bold text-foreground">
                  {ingest_result.media?.length || 0}
                </div>
                <div className="text-sm text-muted-foreground">Media Files</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sample Data Preview */}
      {ingest_result && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Messages Preview */}
          {ingest_result.messages && ingest_result.messages.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-info" />
                  Recent Messages
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-40 overflow-y-auto">
                  {ingest_result.messages.slice(0, 3).map((msg, index) => (
                    <div key={index} className="p-2 bg-surface-1 rounded text-sm">
                      <div className="font-medium text-foreground">Message {index + 1}</div>
                      <div className="text-muted-foreground truncate">
                        {msg.content ? `${msg.content.substring(0, 100)}...` : "No content"}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Contacts Preview */}
          {ingest_result.contacts && ingest_result.contacts.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="w-4 h-4 text-signal" />
                  Contacts
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-40 overflow-y-auto">
                  {ingest_result.contacts.slice(0, 5).map((contact, index) => (
                    <div key={index} className="p-2 bg-surface-1 rounded text-sm">
                      <div className="font-medium text-foreground">
                        {contact.name || `Contact ${index + 1}`}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ALEAPP Reports */}
      {data.aleapp_processed && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ExternalLink className="w-5 h-5 text-signal" />
              ALEAPP Reports
            </CardTitle>
            <CardDescription>
              Android analysis reports generated by ALEAPP
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex items-center justify-between p-3 bg-signal/10 border border-signal/20 rounded-lg">
                <div>
                  <div className="font-medium text-foreground">HTML Report</div>
                  <div className="text-sm text-muted-foreground">Interactive web report</div>
                </div>
                {data.aleapp_web_url && (
                  <a
                    href={data.aleapp_web_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-signal hover:brightness-110 text-sm font-medium"
                  >
                    View Report →
                  </a>
                )}
              </div>
              {data.aleapp_report_path && (
                <div className="text-sm text-muted-foreground">
                  Report saved to: {data.aleapp_report_path}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
