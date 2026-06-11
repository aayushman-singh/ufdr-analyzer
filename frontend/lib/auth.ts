// Authentication client — obtain and store the bearer token that owner-scoped
// endpoints (notably the cross-case link graph) now require.
//
// The token is the proof that the caller is a specific investigating officer;
// the backend binds every link-graph query/export to it, so a missing or wrong
// token is rejected (401/403) rather than silently handed someone else's data.
// Errors are surfaced, never swallowed.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const TOKEN_KEY = "ufdr.access_token"

export interface TokenResponse {
  access_token: string
  token_type: string
  user_id: string
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null
  return window.localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return
  window.localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  if (typeof window === "undefined") return
  window.localStorage.removeItem(TOKEN_KEY)
}

export function isAuthenticated(): boolean {
  return getToken() !== null
}

// Authorization header for authenticated requests; empty when no token is held,
// so the request reaches the server and fails loud with 401 (no silent skip).
export function authHeader(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function postAuth(path: string, body: unknown): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = ""
    try {
      const data = await res.json()
      detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data)
    } catch {
      detail = await res.text().catch(() => "")
    }
    throw new Error(detail || `${res.status} ${res.statusText}`)
  }
  const token = (await res.json()) as TokenResponse
  setToken(token.access_token)
  return token
}

export function login(email: string, password: string): Promise<TokenResponse> {
  return postAuth("/auth/login", { email, password })
}

export function signup(
  username: string,
  email: string,
  password: string,
): Promise<TokenResponse> {
  return postAuth("/auth/signup", { username, email, password })
}
