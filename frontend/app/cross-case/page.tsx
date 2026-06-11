"use client"

import { useState } from "react"
import Link from "next/link"
import {
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
import { Seal } from "@/components/brand/Seal"
import {
  getCrossCaseLinks,
  lookupIdentifier,
  type CrossCaseLinksResponse,
  type IdentifierLookupResponse,
  type IdentifierType,
} from "@/lib/analyticsApi"

function IdentifierIcon({ type }: { type: IdentifierType }) {
  return type === "email" ? (
    <Mail className="h-4 w-4 text-signal" />
  ) : (
    <Phone className="h-4 w-4 text-signal" />
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
      <span className="text-xs italic text-muted-foreground">no other runs</span>
    )
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {runs.map((r) => (
        <span
          key={r}
          className="rounded bg-surface-1 px-1.5 py-0.5 font-mono text-xs text-muted-foreground"
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
    <div className="min-h-screen bg-background">
      <header className="w-full border-b bg-background/80 px-4 py-5 backdrop-blur-md sm:px-8">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Seal size={28} />
            <span className="text-xl font-medium text-foreground">ForensicAI</span>
          </Link>
          <Badge variant="signal">Cross-case Correlation</Badge>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-foreground">
            Cross-case correlation
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Find identifiers that bridge multiple investigations. Identifiers are
            matched on a privacy-preserving salted hash, so cases can be linked
            without exposing the raw phone numbers or emails.
          </p>
        </div>

        {/* Mode (a): links for a run */}
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Link2 className="h-4 w-4 text-signal" />
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
                  className="text-sm font-medium text-foreground"
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
                  className="font-mono"
                />
              </div>
              <Button
                variant="signal"
                onClick={findLinks}
                disabled={linksLoading}
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
                <p className="text-sm text-muted-foreground">
                  {links.link_count} cross-case link
                  {links.link_count === 1 ? "" : "s"} found.
                </p>
                {links.links.length === 0 ? (
                  <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                    No identifiers in this run appear in other cases.
                  </p>
                ) : (
                  links.links.map((l) => (
                    <div
                      key={`${l.identifier_type}:${l.identifier}`}
                      className="rounded-xl border bg-card p-4"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <IdentifierIcon type={l.identifier_type} />
                        <span className="font-mono text-sm font-medium text-foreground">
                          {l.identifier}
                        </span>
                        <Badge variant="signal" className="ml-auto">
                          appears in {l.case_count} case
                          {l.case_count === 1 ? "" : "s"}
                        </Badge>
                      </div>
                      <div className="mt-3 border-t pt-3">
                        <p className="mb-1.5 text-xs font-medium text-muted-foreground">
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
              <Search className="h-4 w-4 text-signal" />
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
                  className="text-sm font-medium text-foreground"
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
                  className="font-mono"
                />
              </div>
              <Button
                variant="signal"
                onClick={runLookup}
                disabled={lookupLoading}
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
              <div className="rounded-xl border bg-card p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium text-foreground">
                    {lookup.identifier}
                  </span>
                  <Badge variant="signal" className="ml-auto">
                    {lookup.count} case{lookup.count === 1 ? "" : "s"}
                  </Badge>
                </div>

                <div className="mt-3 border-t pt-3">
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">
                    Appears in runs
                  </p>
                  <RunIdList runs={lookup.runs} />
                </div>

                <div className="mt-3 flex items-start gap-2 rounded-lg bg-surface-1 p-3">
                  <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal" />
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-foreground">
                      Salted hash (privacy-preserving)
                    </p>
                    <p className="mt-0.5 break-all font-mono text-xs text-muted-foreground">
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
