"use client"

import { useState } from "react"
import Link from "next/link"
import {
  Shield,
  Link2,
  Search,
  Loader2,
  AlertTriangle,
  Phone,
  Mail,
  Lock,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  getCrossCaseLinks,
  lookupIdentifier,
  type CrossCaseLinksResponse,
  type IdentifierLookupResponse,
  type IdentifierType,
} from "@/lib/analyticsApi"

function IdentifierIcon({ type }: { type: IdentifierType }) {
  return type === "email" ? (
    <Mail className="h-4 w-4 text-purple-600" />
  ) : (
    <Phone className="h-4 w-4 text-purple-600" />
  )
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <p className="font-medium">Request failed</p>
        <p className="mt-1 whitespace-pre-wrap break-words font-mono text-xs text-red-700">
          {message}
        </p>
      </div>
    </div>
  )
}

function RunIdList({ runs }: { runs: string[] }) {
  if (runs.length === 0) {
    return (
      <span className="text-xs italic text-slate-400">no other runs</span>
    )
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {runs.map((r) => (
        <span
          key={r}
          className="rounded bg-slate-50 px-1.5 py-0.5 font-mono text-xs text-slate-600"
        >
          {r}
        </span>
      ))}
    </div>
  )
}

export default function CrossCasePage() {
  // Mode (a): links for a run.
  const [runId, setRunId] = useState("")
  const [linksLoading, setLinksLoading] = useState(false)
  const [linksError, setLinksError] = useState<string | null>(null)
  const [links, setLinks] = useState<CrossCaseLinksResponse | null>(null)

  // Mode (b): single-identifier lookup.
  const [identifier, setIdentifier] = useState("")
  const [lookupLoading, setLookupLoading] = useState(false)
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [lookup, setLookup] = useState<IdentifierLookupResponse | null>(null)

  const findLinks = async () => {
    if (!runId.trim()) {
      setLinksError("Enter a Run ID first.")
      return
    }
    setLinksLoading(true)
    setLinksError(null)
    try {
      setLinks(await getCrossCaseLinks(runId.trim()))
    } catch (err) {
      // Do not swallow — surface the backend error text verbatim.
      setLinksError(err instanceof Error ? err.message : String(err))
      setLinks(null)
    } finally {
      setLinksLoading(false)
    }
  }

  const runLookup = async () => {
    if (!identifier.trim()) {
      setLookupError("Enter an identifier first.")
      return
    }
    setLookupLoading(true)
    setLookupError(null)
    try {
      setLookup(await lookupIdentifier(identifier.trim()))
    } catch (err) {
      // Do not swallow — surface the backend error text verbatim.
      setLookupError(err instanceof Error ? err.message : String(err))
      setLookup(null)
    } finally {
      setLookupLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-purple-50 to-white">
      <header className="w-full border-b border-slate-200 bg-white/80 px-4 py-5 backdrop-blur-sm sm:px-8">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-purple-600 to-purple-800">
              <Shield className="h-4 w-4 text-white" />
            </div>
            <span className="text-xl font-medium text-slate-900">ForensicAI</span>
          </Link>
          <Badge variant="secondary" className="bg-purple-100 text-purple-700">
            Cross-case Correlation
          </Badge>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-slate-900">
            Cross-case correlation
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">
            Find identifiers that bridge multiple investigations. Identifiers are
            matched on a privacy-preserving salted hash, so cases can be linked
            without exposing the raw phone numbers or emails.
          </p>
        </div>

        {/* Mode (a): links for a run */}
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Link2 className="h-4 w-4 text-purple-600" />
              Links for a run
            </CardTitle>
            <CardDescription>
              List every identifier in this run that also appears in other cases.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <div className="flex flex-1 flex-col gap-2">
                <label
                  htmlFor="run-id"
                  className="text-sm font-medium text-slate-800"
                >
                  Run ID
                </label>
                <Input
                  id="run-id"
                  value={runId}
                  onChange={(e) => setRunId(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !linksLoading) findLinks()
                  }}
                  placeholder="Extraction run UUID"
                  disabled={linksLoading}
                  className="font-mono focus-visible:ring-purple-500"
                />
              </div>
              <Button
                onClick={findLinks}
                disabled={linksLoading}
                className="bg-slate-900 hover:bg-slate-700"
              >
                {linksLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Link2 className="h-4 w-4" />
                )}
                Find links
              </Button>
            </div>

            {linksError && <ErrorBanner message={linksError} />}

            {links && (
              <div className="space-y-3">
                <p className="text-sm text-slate-600">
                  {links.link_count} cross-case link
                  {links.link_count === 1 ? "" : "s"} found.
                </p>
                {links.links.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
                    No identifiers in this run appear in other cases.
                  </p>
                ) : (
                  links.links.map((l) => (
                    <div
                      key={`${l.identifier_type}:${l.identifier}`}
                      className="rounded-xl border border-slate-200 bg-white p-4"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <IdentifierIcon type={l.identifier_type} />
                        <span className="font-mono text-sm font-medium text-slate-900">
                          {l.identifier}
                        </span>
                        <Badge
                          variant="secondary"
                          className="ml-auto bg-purple-100 text-purple-700"
                        >
                          appears in {l.case_count} case
                          {l.case_count === 1 ? "" : "s"}
                        </Badge>
                      </div>
                      <div className="mt-3 border-t border-slate-100 pt-3">
                        <p className="mb-1.5 text-xs font-medium text-slate-500">
                          Also in runs
                        </p>
                        <RunIdList runs={l.also_in_runs} />
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Mode (b): single-identifier lookup */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Search className="h-4 w-4 text-purple-600" />
              Identifier lookup
            </CardTitle>
            <CardDescription>
              Check which cases a single phone number or email appears in.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <div className="flex flex-1 flex-col gap-2">
                <label
                  htmlFor="identifier"
                  className="text-sm font-medium text-slate-800"
                >
                  Identifier
                </label>
                <Input
                  id="identifier"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !lookupLoading) runLookup()
                  }}
                  placeholder="+15551234567 or name@example.com"
                  disabled={lookupLoading}
                  className="font-mono focus-visible:ring-purple-500"
                />
              </div>
              <Button
                onClick={runLookup}
                disabled={lookupLoading}
                className="bg-slate-900 hover:bg-slate-700"
              >
                {lookupLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
                Look up
              </Button>
            </div>

            {lookupError && <ErrorBanner message={lookupError} />}

            {lookup && (
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium text-slate-900">
                    {lookup.identifier}
                  </span>
                  <Badge
                    variant="secondary"
                    className="ml-auto bg-purple-100 text-purple-700"
                  >
                    {lookup.count} case{lookup.count === 1 ? "" : "s"}
                  </Badge>
                </div>

                <div className="mt-3 border-t border-slate-100 pt-3">
                  <p className="mb-1.5 text-xs font-medium text-slate-500">
                    Appears in runs
                  </p>
                  <RunIdList runs={lookup.runs} />
                </div>

                <div className="mt-3 flex items-start gap-2 rounded-lg bg-slate-50 p-3">
                  <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-slate-600">
                      Salted hash (privacy-preserving)
                    </p>
                    <p className="mt-0.5 break-all font-mono text-xs text-slate-500">
                      {lookup.identifier_hash}
                    </p>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  )
}
