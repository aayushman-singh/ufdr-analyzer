# Dashboard Evidence Search Design

## User Outcome

An investigator can search the active extraction run from the dashboard Evidence Search tab and see cited evidence rows returned by the auditable query pipeline. The tab no longer claims fake result counts or shows canned messages.

## Success Criteria

- The search form reads the active `run_id` from browser storage.
- Submitting a non-empty query calls `runQueryPlan({ question, run_id, context })`.
- Returned rows display source table, timestamp, preview text, and citation snippets.
- The result count comes from `QueryPlanResponse.total`.
- Missing `run_id`, empty query, and API errors are shown explicitly.
- Content type and date controls affect the submitted question/context visibly; they do not filter local mock data.
- No static `searchResults` array remains.

## Non-Goals

- No new backend endpoint.
- No cross-case/global search behavior.
- No report generation or graph rewiring.
- No silent fallback to canned search results.

## Hard Constraints

- Use the existing `frontend/lib/queryPlanApi.ts` client.
- Keep the change scoped to `frontend/components/dashboard/views/EvidenceSearchView.tsx`.
- Preserve loud failure behavior.
- Do not introduce a frontend test framework for this slice.

## Design

`EvidenceSearchView` becomes a client component. It stores the query text, selected content scopes, date range inputs, request state, error, and latest query response. On submit it validates the query and `run_id`, builds an explicit search question from the user's text plus selected scopes/date range, and sends it through `runQueryPlan`.

The UI renders loading, error, empty, and result states. Result cards are backed by `ResultRow` data and show citations so a reviewer can see why a row matched. Filter controls are honest query-shaping controls, not client-side filtering over fake data.

## Testing And Verification

- Run ESLint on `components/dashboard/views/EvidenceSearchView.tsx`.
- Run `npx tsc --noEmit`.
- Run `npm run lint` and `npm run build`; record unrelated repo failures if they remain.
