# Dashboard Data Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the dashboard Data Visualization tab to real analytics for the active extraction run.

**Architecture:** Keep the existing React view and existing `getPatterns(runId)` client. Add a small pure mapper in the view file so API data is converted into chart rows in one place, then render loading, error, empty, grid, and chart states from one analytics state object.

**Tech Stack:** Next.js 15, React 19, TypeScript, Recharts, existing shadcn-style components, existing `frontend/lib/analyticsApi.ts`.

## Global Constraints

- Do not create a new backend endpoint.
- Do not preserve mock activity data as a fallback.
- Missing `run_id` must be shown as a visible error.
- Failed analytics requests must surface the backend/client error message.
- Keep the change scoped to `frontend/components/dashboard/views/DataVisualizationView.tsx`.

---

### Task 1: Wire Real Analytics Into Data Visualization

**Files:**
- Modify: `frontend/components/dashboard/views/DataVisualizationView.tsx`

**Interfaces:**
- Consumes: `getPatterns(runId: string): Promise<PatternsResponse>` from `frontend/lib/analyticsApi.ts`.
- Produces: dashboard chart rows shaped as `{ date: string; calls: number; messages: number; total: number }`.

- [ ] **Step 1: Add the client data state**

Import `useEffect`, `getPatterns`, `PatternsResponse`, `Loader2`, and `AlertTriangle`. Add state for `patterns`, `loading`, and `error`.

- [ ] **Step 2: Load analytics for the active run**

In `useEffect`, read `window.localStorage.getItem("run_id")`. If missing, set error `"No active analysis session found. Upload or reset a case first."`. If present, call `getPatterns(runId)` and store the response. If it throws, store `err instanceof Error ? err.message : String(err)`.

- [ ] **Step 3: Replace mock chart rows**

Delete `mockChartData`. Create chart rows from `patterns?.daily_series ?? []`, preserving `date`, `calls`, `messages`, and `total`.

- [ ] **Step 4: Render explicit states**

Show a loading panel while loading. Show an error panel with a Retry button when `error` is set. Show an empty state when the API succeeds with no `daily_series`.

- [ ] **Step 5: Update visible summaries**

Replace static activity copy with totals derived from `patterns.total_events`, `patterns.findings.length`, and the loaded daily series.

- [ ] **Step 6: Verify**

Run:

```bash
cd frontend
npm run lint
npm run build
```

Expected: both commands complete successfully.
