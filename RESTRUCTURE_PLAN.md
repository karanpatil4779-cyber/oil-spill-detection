# SIH2026 Oil Spill Platform — Restructure Plan

## Current State
- Single React page (`App.jsx`, 367 lines) — no auth, no roles
- FastAPI backend (`main.py`) — 3 routes only
- SQLAlchemy DB — 4 models (Incident, Detection, TransportResult, AttributionResult)
- Full 6-stage science pipeline in `engines/` — solid, keep as-is
- No login, no dashboard separation, no report generation

## Target State
3-role platform (Analyst / Supervisor / Admin) per your specification above.

---

## Phase 0: Backend Foundation — Auth, Users, Cases

### New DB Models (`apps/db/models.py`)
```
+ User             (id, email, name, role[analyst|supervisor|admin], status, password_hash, created_at, last_login)
+ Case             (id, incident_id, analyst_id, status[in_progress|pending_review|returned|approved|closed|insufficient_evidence], created_at, updated_at)
+ CaseNote         (id, case_id, author_id, content, created_at)  — supervisor notes, analyst notes
+ AuditLogEntry    (id, case_id|null, actor_id, action_type, detail, timestamp)  — immutable, analyst can't edit
+ ModelVersion     (id, model_type[detection|transport|attribution], version_tag, is_active, deployed_by, deployed_at)
+ DataSourceConfig (id, source_type[satellite|ais|metocean], endpoint, credentials_ref, refresh_interval, updated_by, updated_at)
+ Report           (id, case_id, generated_by, generated_at, pdf_path)
```

### New API Routes (`apps/api/main.py` or split into `apps/api/routes/`)

#### Auth Routes
- `POST /auth/login` → JWT access + refresh token
- `POST /auth/refresh` → refresh access token
- `GET /auth/me` → current user profile + role

#### User Management (Admin only)
- `GET /admin/users` — list all accounts
- `POST /admin/users` — create account (with role assignment)
- `PATCH /admin/users/:id` — reassign role / deactivate
- `GET /admin/audit-log` — search system-level audit entries

#### System Config (Admin only)
- `GET /admin/data-sources` — list configured feeds
- `PUT /admin/data-sources/:id` — update feed config
- `GET /admin/models` — list model versions
- `POST /admin/models/deploy` — deploy new version
- `POST /admin/models/:id/rollback` — rollback to previous

#### Case Routes (shared, permission-scoped)
- `GET /cases` — analyst sees own cases; supervisor sees all
- `POST /cases` — analyst creates new investigation (triggers pipeline)
- `GET /cases/:id` — read-only full case data (all 8 panels)
- `PATCH /cases/:id/status` — status transitions (analyst: submit for review; supervisor: approve/return/escalate)
- `POST /cases/:id/notes` — add note
- `POST /cases/:id/rerun` — re-run a specific stage (analyst only)
- `POST /cases/:id/report` — generate PDF report
- `GET /cases/:id/audit` — audit trail for a case

#### Supervisor Analytics
- `GET /analytics/throughput` — cases per week, avg resolution time
- `GET /analytics/candidate-ratios` — AIS filter performance
- `GET /analytics/evidence-rate` — insufficient evidence outcomes
- `GET /analytics/analyst-performance` — optional breakdown

#### Detection/Pipeline (existing, wrapped with auth)
- `POST /attribute/spill` — existing pipeline, now behind auth + creates Case record
- `GET /sar/search` — existing, unchanged

### Middleware
- JWT auth middleware on all routes except `/auth/login` and `/health`
- Role-check dependency: `require_role("analyst")`, `require_role("supervisor")`, `require_role("admin")`
- Audit logger: writes to `AuditLogEntry` on every state-changing action

---

## Phase 1: Frontend Structure — Routing + Layout

### New Directory Structure (`apps/web/src/`)
```
src/
├── main.jsx                    — ReactDOM entry, router setup
├── App.jsx                     — Router shell (replaces current 367-line monolith)
├── index.css                   — global dark theme (extend existing)
│
├── api/
│   └── client.js               — fetch wrapper with JWT token management
│
├── auth/
│   ├── AuthContext.jsx          — React context: user, role, login/logout
│   └── ProtectedRoute.jsx      — route guard by role
│
├── layouts/
│   ├── AnalystLayout.jsx        — sidebar (own cases) + main panel
│   ├── SupervisorLayout.jsx     — sidebar (all cases + analytics tab) + main panel
│   └── AdminLayout.jsx          — sidebar (users, config, models, audit) + main panel
│
├── pages/
│   ├── LoginPage.jsx            — email/password form, role-based redirect
│   │
│   ├── analyst/
│   │   ├── Dashboard.jsx        — case list (own), filter by status, "+ New Investigation"
│   │   ├── NewInvestigation.jsx — date/time/location search + satellite scene upload
│   │   └── Workspace.jsx        — single scrollable page, 8 panels (THE core UI)
│   │
│   ├── supervisor/
│   │   ├── PortfolioDashboard.jsx — all cases table, sortable/filterable
│   │   ├── CaseReview.jsx        — same 8 panels, read-only
│   │   └── Analytics.jsx         — aggregate metrics dashboard
│   │
│   └── admin/
│       ├── SystemDashboard.jsx   — pipeline health traffic lights
│       ├── UserManagement.jsx    — account table + create/edit
│       ├── DataSourceConfig.jsx  — feed endpoints + credentials
│       ├── ModelRegistry.jsx     — model versions + deploy/rollback
│       └── AuditLog.jsx          — searchable system audit log
│
├── components/
│   ├── MapView.jsx              — shared Mapbox component (extracted from current App.jsx)
│   ├── CaseTable.jsx            — reusable filterable table (used by all 3 dashboards)
│   ├── StatusBadge.jsx          — colored status pill
│   ├── ConfidenceGauge.jsx      — score visualization
│   │
│   ├── workspace/
│   │   ├── Panel1Detection.jsx
│   │   ├── Panel2Characterization.jsx
│   │   ├── Panel3OriginHindcast.jsx
│   │   ├── Panel4ForwardForecast.jsx
│   │   ├── Panel5AISVessels.jsx
│   │   ├── Panel6Attribution.jsx
│   │   ├── Panel7DataQuality.jsx
│   │   └── Panel8AuditTrail.jsx
│   │
│   ├── supervisor/
│   │   ├── DecisionBar.jsx      — Approve / Return / Escalate / Add Note
│   │   └── ReviewHeader.jsx     — supervisor note pinned at top
│   │
│   └── admin/
│       ├── HealthIndicator.jsx  — green/amber/red traffic light
│       └── ModelDeployDialog.jsx
│
└── utils/
    ├── constants.js              — status enums, role enums
    └── formatters.js             — date, confidence, area formatters
```

---

## Phase 2: Analyst Workspace — The 8 Panels

All panels live inside `Workspace.jsx` as a single scrollable page. Panel component files contain the view logic; `Workspace.jsx` orchestrates state.

### Panel 1 — Detection Result
- `MapView.jsx` showing satellite scene + candidate spill polygon
- Confidence score + look-alike flag display
- **Action**: "Mark as False Positive" button → closes case

### Panel 2 — Characterization
- Area, perimeter, centroid, shape/morphology
- Age estimate as range with confidence interval
- **Action**: "Re-segment" button → triggers pipeline re-run with adjusted params

### Panel 3 — Origin / Hindcast
- Shaded probable-origin region (uncertainty ellipse) on map
- Probable time window display
- **Action**: dropdown to change metocean forcing source + re-run button

### Panel 4 — Forward Forecast
- 24/48/72-hr spread projection as widening cone
- **Action**: adjustable forecast horizon slider

### Panel 5 — AIS / Vessel Candidates
- Vessel list with tracks, AIS gaps, dark-fleet flags
- Candidate reduction ratio display
- **Action**: filter threshold sliders + re-run candidate search

### Panel 6 — Attribution Ranking
- Ranked candidates with per-factor evidence breakdown
- "Highest-ranked probable source" label
- **Action**: manual rank override with justification (logged)

### Panel 7 — Data Quality & Confidence Summary
- Overall case confidence, satellite quality, AIS completeness
- **Action**: "Insufficient Evidence" button → closes case honestly

### Panel 8 — Audit Panel
- Read-only log of all re-runs, parameter changes, overrides
- Auto-generated, not editable

---

## Phase 3: Supervisor Review

### PortfolioDashboard.jsx
- Same table structure as analyst dashboard but shows ALL analysts' cases
- Sortable by incident age (oldest first)
- Tabs: Cases | Analytics

### CaseReview.jsx
- Reuses all 8 Panel components from `components/workspace/` but renders them without action buttons
- `DecisionBar.jsx` fixed at bottom: Approve / Return for Revision / Escalate / Add Note
- "Return" opens required note field (can't submit empty)
- Supervisor note pinned at top of workspace

### Analytics.jsx
- Charts/metrics: case throughput, candidate-reduction ratios, insufficient-evidence rate, analyst breakdown
- Uses a charting library (chart.js or recharts)

---

## Phase 4: Admin Panel

### SystemDashboard.jsx
- Traffic-light grid: satellite feed, AIS feed, metocean feed
- Job queue stats: running/queued/failed
- No case data visible

### UserManagement.jsx
- CRUD table for accounts
- Role assignment dropdown
- Create Admin triggers confirmation step

### DataSourceConfig.jsx
- Edit endpoints, credentials, polling intervals for each feed

### ModelRegistry.jsx
- Table: model_type, version_tag, is_active, deployed_at
- Deploy New Version button
- Rollback button per row

### AuditLog.jsx
- Searchable table: timestamp, actor, action_type, detail
- Explicitly no case content

---

## Phase 5: Report Generation

### Backend
- `POST /cases/:id/report` → compiles all panel data into structured JSON
- PDF generation using `weasyprint` or `reportlab`
- Store PDF on disk + return download URL

### Frontend
- "Generate Report" button in workspace (analyst) / "Export" button in review (supervisor)
- Downloads PDF

---

## Implementation Order (recommended build sequence)

| Step | What | Files | Est. Effort |
|------|------|-------|-------------|
| 1 | Auth system (login, JWT, middleware) | `models.py`, new auth routes, `AuthContext.jsx`, `LoginPage.jsx` | 1 day |
| 2 | Case model + CRUD routes | `models.py`, case routes | 0.5 day |
| 3 | Frontend routing + 3 layouts + `ProtectedRoute` | `App.jsx` rewrite, layouts, `main.jsx` | 0.5 day |
| 4 | Analyst Dashboard | `Dashboard.jsx`, `CaseTable.jsx` | 0.5 day |
| 5 | New Investigation page | `NewInvestigation.jsx`, wire to existing `/attribute/spill` | 0.5 day |
| 6 | Workspace — extract MapView + build 8 panels | `Workspace.jsx`, 8 panel components | 2 days |
| 7 | Supervisor Dashboard + CaseReview | `PortfolioDashboard.jsx`, `CaseReview.jsx`, `DecisionBar.jsx` | 1 day |
| 8 | Analytics tab | `Analytics.jsx` + charting lib | 0.5 day |
| 9 | Admin pages (lightweight) | 5 admin pages (mockup-realistic) | 1 day |
| 10 | Report PDF generation | Backend PDF endpoint + frontend download | 0.5 day |
| 11 | Audit logging middleware | Backend middleware | 0.5 day |
| 12 | Polish + integration testing | end-to-end flow testing | 1 day |
| | **Total** | | **~9 days** |

---

## Key Technical Decisions

1. **Router**: `react-router-dom` v6 (add to package.json)
2. **State management**: React Context (auth) + component state (no Redux needed at this scale)
3. **Charts**: `recharts` (lightweight, React-native)
4. **PDF**: `weasyprint` (Python) or `@react-pdf/renderer` (JS) — TBD
5. **JWT**: `python-jose` + `passlib[bcrypt]` on backend
6. **All existing engines/ untouched** — they become the backend service layer behind the new API routes
7. **Keep SQLite fallback** for demo; Postgres for production
