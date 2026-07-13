"use client"

import { Mail, Lock } from "lucide-react"
import { Seal } from "@/components/brand/Seal"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { Suspense, useState } from "react"
import { login } from "@/lib/auth"

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  )
}

function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(email, password)
      const next = searchParams.get("next")
      router.push(next && next.startsWith("/") ? next : "/query-plan")
    } catch (err) {
      // Surface the failure loudly — no silent retry, no fake "success".
      setError(err instanceof Error ? err.message : "Sign in failed.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="theme-light min-h-screen w-full bg-background relative overflow-hidden">
      {/* Background grid + signal radial */}
      <div className="fixed inset-0 z-0 bg-grid">
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(circle 800px at 0% 200px, color-mix(in oklch, var(--signal) 12%, transparent), transparent)",
          }}
        />
      </div>

      {/* Header with ForensicAI branding */}
      <header className="relative z-10 w-full px-8 py-6">
        <div className="max-w-7xl mx-auto">
          <Link href="/" className="flex items-center space-x-2 w-fit">
            <Seal size={28} />
            <span className="text-xl font-medium text-foreground">ForensicAI</span>
          </Link>
        </div>
      </header>

      {/* Main Content - Centered Login Form */}
      <main className="relative z-10 flex items-center justify-center min-h-[calc(100vh-120px)] px-4">
        <div className="w-full max-w-md">
          {/* Seal splash */}
          <div className="flex justify-center mb-6">
            <Seal size={72} glow />
          </div>

          {/* Card Container */}
          <div className="bg-card rounded-2xl shadow-lg border border-border p-8">
            {/* Welcome Back Header */}
            <div className="text-center mb-8">
              <h1 className="text-2xl font-semibold text-foreground mb-2">Welcome Back</h1>
              <p className="text-muted-foreground">Sign in to continue to your dashboard.</p>
            </div>

            {/* Login Form */}
            <form className="space-y-6" onSubmit={handleSubmit}>
              {/* Email Field */}
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-foreground mb-2">
                  Email Address
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Mail className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <input
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="block w-full pl-10 pr-3 py-3 border border-border rounded-lg bg-surface-1 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-[var(--ring)] focus:border-transparent"
                    placeholder="you@example.com"
                  />
                </div>
              </div>

              {/* Password Field */}
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-foreground mb-2">
                  Password
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Lock className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <input
                    id="password"
                    name="password"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="block w-full pl-10 pr-3 py-3 border border-border rounded-lg bg-surface-1 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-[var(--ring)] focus:border-transparent"
                    placeholder="••••••••"
                  />
                </div>
              </div>

              {error && (
                <p role="alert" className="text-sm text-[var(--severity-high)]">
                  {error}
                </p>
              )}

              {/* Sign In Button */}
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-signal text-signal-foreground py-3 px-4 rounded-lg font-medium hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-[var(--ring)] focus:ring-offset-2 transition-all disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {loading ? "Signing In..." : "Sign In"}
              </button>
            </form>

            {/* Sign Up Link */}
            <div className="mt-6 text-center">
              <p className="text-muted-foreground">
                Don&apos;t have an account?{" "}
                <Link href="/signup" className="text-signal hover:brightness-90 font-medium">
                  Sign Up
                </Link>
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
