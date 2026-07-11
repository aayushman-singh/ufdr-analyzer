# Dashboard Data Visualization Design

## User Outcome

An investigator opening the dashboard Data Visualization tab sees activity charts from the active extraction run, not canned sample data. If no run is active or the analytics API rejects the request, the tab shows the explicit failure reason and stops dependent rendering.

## Success Criteria

- The view reads the active `run_id` from browser storage, matching the dashboard AI assistant's current session convention.
- The communication chart uses `GET /analytics/patterns` via the existing `getPatterns(runId)` client.
- The chart renders real `daily_series` rows for messages and calls.
- The view does not preserve mock activity values when real analytics are unavailable.
- Missing run IDs and failed analytics requests are visible in the UI.
- Existing dashboard navigation and styling remain intact.

## Non-Goals

- No new backend endpoints.
- No implementation of the unused backend AI placeholder modules.
- No global search, evidence search, report, or graph rewiring in this slice.
- No silent degraded mode or fake replacement data.

## Hard Constraints

- Reuse the existing `frontend/lib/analyticsApi.ts` API contract.
- Keep changes scoped to the dashboard data visualization surface unless a small pure helper is needed for testability.
- Preserve loud failure behavior: do not catch an analytics error and render canned data.
- Keep paths and code cross-platform; do not hardcode path separators.

## Design

`DataVisualizationView` becomes a client-side data consumer for the active run. On mount it reads `localStorage.run_id`; if absent, it records a visible error state. If present, it calls `getPatterns(runId)`, maps `daily_series` into chart rows, and derives summary counts from that same response.

The view keeps the existing grid and chart modes, but the communication card and chart are backed by loaded analytics data. Loading, error, and empty-data states are explicit. Empty analytics are treated as a real empty result, not as a reason to show mock rows.

## Testing And Verification

- Typecheck/lint the frontend after implementation.
- Build the frontend to catch Next.js client/server and chart rendering issues.
- Manually inspect the view logic for no remaining `mockChartData` dependency.
