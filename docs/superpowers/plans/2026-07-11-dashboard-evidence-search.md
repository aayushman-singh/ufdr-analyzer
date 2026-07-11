# Dashboard Evidence Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the dashboard Evidence Search tab to the auditable query pipeline for the active run.

**Architecture:** Convert `EvidenceSearchView` into a client component that submits a shaped natural-language query to `runQueryPlan`. Render all result, loading, empty, and error states from the API response, with no local mock result data.

**Tech Stack:** Next.js 15, React 19, TypeScript, existing query plan API client, existing UI components.

## Global Constraints

- Do not add backend endpoints.
- Do not preserve mock search results.
- Missing `run_id` and request failures must be visible in the UI.
- Keep the implementation scoped to `frontend/components/dashboard/views/EvidenceSearchView.tsx`.

---

### Task 1: Replace Mock Evidence Search With Query Plan Results

**Files:**
- Modify: `frontend/components/dashboard/views/EvidenceSearchView.tsx`

**Interfaces:**
- Consumes: `runQueryPlan(body: QueryPlanRequest): Promise<QueryPlanResponse>`.
- Produces: dashboard search UI that renders `QueryPlanResponse.rows`.

- [ ] **Step 1: Convert the component to a client component**

Add `"use client"`, `useMemo`, and `useState`.

- [ ] **Step 2: Add form state**

Track query text, selected content scopes, start date, end date, loading, error, and `QueryPlanResponse | null`.

- [ ] **Step 3: Build the submitted question**

Create a helper that appends selected scopes and date range to the user's text in plain English.

- [ ] **Step 4: Submit through the query plan API**

Read `localStorage.run_id`, validate it exists, call `runQueryPlan`, and store the response. On failure, clear response and store the error message.

- [ ] **Step 5: Render API-backed result states**

Replace the static `searchResults` map with cards from `response.rows`. Show source table, event time, preview, citations, and total count.

- [ ] **Step 6: Verify**

Run:

```bash
cd frontend
npx eslint components/dashboard/views/EvidenceSearchView.tsx
npx tsc --noEmit
npm run lint
npm run build
```
