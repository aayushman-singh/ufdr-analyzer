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
            <FileText className="w-5 h-5 text-purple-500" />
            Processing Summary
          </CardTitle>
          <CardDescription>
            Details about the file processing and analysis
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-gray-500">Filename</label>
              <p className="text-sm">{data.filename}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-500">Processing Time</label>
              <p className="text-sm">{data.processing_time}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-500">Status</label>
              <Badge variant={data.status === "success" ? "default" : "destructive"}>
                {data.status}
              </Badge>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-500">ALEAPP Processed</label>
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
              <Database className="w-5 h-5 text-blue-500" />
              Data Statistics
            </CardTitle>
            <CardDescription>
              Extracted data counts and analysis results
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center p-4 bg-blue-50 rounded-lg">
                <div className="text-2xl font-bold text-blue-600">
                  {ingest_result.messages?.length || 0}
                </div>
                <div className="text-sm text-blue-600">Messages</div>
              </div>
              <div className="text-center p-4 bg-green-50 rounded-lg">
                <div className="text-2xl font-bold text-green-600">
                  {ingest_result.contacts?.length || 0}
                </div>
                <div className="text-sm text-green-600">Contacts</div>
              </div>
              <div className="text-center p-4 bg-orange-50 rounded-lg">
                <div className="text-2xl font-bold text-orange-600">
                  {ingest_result.calls?.length || 0}
                </div>
                <div className="text-sm text-orange-600">Call Records</div>
              </div>
              <div className="text-center p-4 bg-purple-50 rounded-lg">
                <div className="text-2xl font-bold text-purple-600">
                  {ingest_result.media?.length || 0}
                </div>
                <div className="text-sm text-purple-600">Media Files</div>
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
                  <FileText className="w-4 h-4 text-blue-500" />
                  Recent Messages
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-40 overflow-y-auto">
                  {ingest_result.messages.slice(0, 3).map((msg, index) => (
                    <div key={index} className="p-2 bg-gray-50 rounded text-sm">
                      <div className="font-medium">Message {index + 1}</div>
                      <div className="text-gray-600 truncate">
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
                  <Database className="w-4 h-4 text-green-500" />
                  Contacts
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-40 overflow-y-auto">
                  {ingest_result.contacts.slice(0, 5).map((contact, index) => (
                    <div key={index} className="p-2 bg-gray-50 rounded text-sm">
                      <div className="font-medium">
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
              <ExternalLink className="w-5 h-5 text-purple-500" />
              ALEAPP Reports
            </CardTitle>
            <CardDescription>
              Android analysis reports generated by ALEAPP
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex items-center justify-between p-3 bg-purple-50 rounded-lg">
                <div>
                  <div className="font-medium">HTML Report</div>
                  <div className="text-sm text-gray-600">Interactive web report</div>
                </div>
                {data.aleapp_web_url && (
                  <a
                    href={data.aleapp_web_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-purple-600 hover:text-purple-800 text-sm font-medium"
                  >
                    View Report →
                  </a>
                )}
              </div>
              {data.aleapp_report_path && (
                <div className="text-sm text-gray-600">
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
