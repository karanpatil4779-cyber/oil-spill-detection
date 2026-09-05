# API Contract — Marine Oil-Spill Investigation Platform

> Auto-generated from actual route definitions. All endpoints require JWT Bearer token unless noted.

---

## Authentication

### `POST /auth/login`
- **Auth:** None
- **Body:** `{ "email": string, "password": string }`
- **Response 200:** `{ "access_token": string, "token_type": "bearer", "user": { "id", "email", "name", "role" } }`
- **Response 401:** `{ "detail": "Invalid credentials" }`

### `GET /auth/me`
- **Auth:** Any authenticated user
- **Response 200:** `{ "id": int, "email": string, "name": string, "role": "analyst"|"supervisor"|"admin", "status": "active"|"deactivated" }`

---

## Cases

### `GET /cases`
- **Auth:** Any authenticated user
- **Query:** `?status_filter=in_progress`
- **Behavior:** Analyst sees own cases only; Supervisor sees all; Admin sees empty list (no investigation data)
- **Response 200:** `{ "cases": [CaseResponse], "total": int }`

### `POST /cases`
- **Auth:** Analyst only
- **Body:** `{ "lon": float, "lat": float, "detection_date": string, "duration_hours"?: int, "location_name"?: string }`
- **Response 201:** CaseResponse

### `GET /cases/{case_id}`
- **Auth:** Analyst (own cases only), Supervisor (all); Admin blocked (403)
- **Response 200:** CaseResponse
- **Response 403:** If not your case or admin

### `PATCH /cases/{case_id}/status`
- **Auth:** Analyst / Supervisor / Admin
- **Body:** `{ "status": string }`
- **Valid transitions:**
  - Analyst: `in_progress → pending_review|insufficient_evidence|closed`, `returned → pending_review|insufficient_evidence|closed`
  - Supervisor: `pending_review → approved|returned`, `approved → closed`
  - Admin: any transition
- **Response 200:** `{ "message": string, "case_id": int }`

### `POST /cases/{case_id}/run-pipeline`
- **Auth:** Analyst (own cases)
- **Behavior:** Legacy synchronous background task (kept for backward compat)
- **Response 200:** `{ "message": "Pipeline started in background", ... }`

### `POST /cases/{case_id}/rerun`
- **Auth:** Analyst (own cases)
- **Body:** `{ "stage": string, "params"?: dict }`
- **Response 200:** `{ "message": string, "case_id": int }`

### `POST /cases/{case_id}/notes`
- **Auth:** Any authenticated user (analyst restricted to own cases)
- **Body:** `{ "content": string }`
- **Response 201:** NoteResponse

### `GET /cases/{case_id}/notes`
- **Auth:** Any authenticated user (analyst restricted to own cases)
- **Response 200:** `[NoteResponse]`

### `POST /cases/{case_id}/return`
- **Auth:** Supervisor only
- **Body:** `{ "content": string }` (non-empty required)
- **Response 200:** `{ "message": "Case returned for revision", "case_id": int }`

### `POST /cases/{case_id}/approve`
- **Auth:** Supervisor only
- **Response 200:** `{ "message": "Case approved", "case_id": int }`

### `POST /cases/{case_id}/escalate`
- **Auth:** Supervisor only
- **Body:** `{ "content": string }`
- **Response 200:** `{ "message": "Case escalated", "case_id": int }`

### `POST /cases/{case_id}/override-rank`
- **Auth:** Analyst (own cases)
- **Body:** `{ "vessel_id": string, "new_rank": int, "justification": string }`
- **Response 200:** `{ "message": "Rank override logged", "case_id": int }`

### `POST /cases/{case_id}/generate-report`
- **Auth:** Any authenticated user (analyst restricted to own cases)
- **Behavior:** **Requires case status `approved`** (supervisor approval gate enforced server-side)
- **Response 200:** `{ "message": "Report generated", "case_number": string, "pdf_path": string }`
- **Response 400:** `"Report generation requires supervisor approval"`

### `GET /cases/{case_id}/audit`
- **Auth:** Any authenticated user (analyst restricted to own cases)
- **Response 200:** `[{ "id": int, "actor": string, "action_type": string, "detail": dict|null, "timestamp": string }]`

---

## Async Pipeline Runs (Milestone 1)

### `POST /cases/{case_id}/runs`
- **Auth:** Analyst (own cases)
- **Body:** `{ "run_sar"?: bool, "sar_date"?: string }`
- **Behavior:** Creates and enqueues async pipeline run. Returns 202 immediately; pipeline runs on background thread.
- **Response 202:** RunResponse
- **Response 409:** If a run is already active (queued/running) for this case

### `GET /cases/{case_id}/runs`
- **Auth:** Any authenticated user (analyst restricted to own cases)
- **Response 200:** `[RunResponse]`

### `GET /cases/{case_id}/runs/{run_id}`
- **Auth:** Any authenticated user (analyst restricted to own cases)
- **Response 200:** RunResponse
- **Response 404:** Run not found

### `POST /cases/{case_id}/runs/{run_id}/cancel`
- **Auth:** Analyst (own cases)
- **Behavior:** Queued runs cancel immediately; running runs set cancel flag picked up at next stage boundary
- **Response 200:** RunResponse
- **Response 409:** Run cannot be cancelled in current state

---

## Supervisor Analytics

### `GET /analytics/throughput`
- **Auth:** Supervisor, Admin
- **Response 200:** `{ "total_cases": int, "by_status": { "in_progress": int, ... } }`

### `GET /analytics/candidate-ratios`
- **Auth:** Supervisor, Admin
- **Response 200:** `{ "cases": [{ "case_number": string, "candidates_found": int }], "count": int }`

### `GET /analytics/evidence-rate`
- **Auth:** Supervisor, Admin
- **Response 200:** `{ "total": int, "insufficient_evidence": int, "closed": int, "approved": int, "insufficient_rate": float }`

### `GET /analytics/analyst-performance`
- **Auth:** Supervisor, Admin
- **Response 200:** `{ "analysts": [{ "analyst_name": string, "total_cases": int, "approved": int, "approval_rate": float }] }`

---

## Admin — User Management

### `GET /admin/users`
- **Auth:** Admin only
- **Response 200:** `[{ "id": int, "email": string, "name": string, "role": string, "status": string, "created_at": string, "last_login": string|null }]`

### `POST /admin/users`
- **Auth:** Admin only
- **Body:** `{ "email": string, "name": string, "password": string, "role": "analyst"|"supervisor"|"admin" }`
- **Behavior:** Creating another admin requires same role (enforced server-side)
- **Response 201:** UserResponse

### `PATCH /admin/users/{user_id}`
- **Auth:** Admin only
- **Body:** `{ "role"?: string, "status"?: string }`
- **Response 200:** UserResponse

---

## Admin — Data Sources

### `GET /admin/data-sources`
- **Auth:** Admin only
- **Response 200:** `[{ "id": int, "source_type": string, "name": string, "endpoint": string|null, "refresh_interval_minutes": int, "is_active": bool, "updated_at": string }]`

### `PUT /admin/data-sources/{source_id}`
- **Auth:** Admin only
- **Body:** DataSourceRequest
- **Response 200:** DataSourceResponse

---

## Admin — Model Registry

### `GET /admin/models`
- **Auth:** Admin only
- **Response 200:** `[ModelVersionResponse]`

### `POST /admin/models/deploy`
- **Auth:** Admin only
- **Body:** `{ "model_type": string, "version_tag": string, "notes"?: string }`
- **Behavior:** Deactivates previous active version of same type
- **Response 201:** ModelVersionResponse

### `POST /admin/models/{model_id}/rollback`
- **Auth:** Admin only
- **Response 200:** ModelVersionResponse

---

## Admin — System Status

### `GET /admin/system-status`
- **Auth:** Admin only
- **Response 200:** `{ "database": string, "providers": dict, "job_runner": { "max_concurrent": int, "max_retries": int, "timeout_seconds": int, "running": int, "queued": int, "failed_total": int } }`
- **Note:** No investigation data exposed. Provider status is from startup checks.

---

## Admin — System Audit Log

### `GET /admin/audit-log`
- **Auth:** Admin only
- **Query:** `?action_type=pipeline_run&limit=100`
- **Response 200:** `[AuditEntryResponse]`

---

## Legacy Routes (no auth)

### `GET /`
- **Response 200:** `{ "message": "Marine Oil-Spill Attribution API is running.", "stages": [...] }`

### `GET /health`
- **Response 200:** `{ "status": "ok" }`

### `POST /attribute/spill`
- **Auth:** None (legacy)
- **Body:** `{ "lon": float, "lat": float, "detection_time": string, "duration_hours"?: int, "incident_id"?: string, "run_sar"?: bool }`
- **Behavior:** Runs pipeline synchronously. **Blocks HTTP request.** Use `/cases/{id}/runs` instead.

### `GET /sar/search`
- **Auth:** None (legacy)
- **Query:** `?lon=...&lat=...&date=...`

---

## Response Shapes

### CaseResponse
```json
{
  "id": 1,
  "case_number": "INC-2026-0001",
  "analyst_name": "Ravi Kumar",
  "status": "in_progress",
  "location_name": "Mumbai Coast",
  "lon": 72.8,
  "lat": 18.9,
  "detection_date": "2018-01-30",
  "overall_confidence": 0.75,
  "pipeline_result": { /* full pipeline output blob */ },
  "pipeline_status": "idle|running|done|error",
  "created_at": "2026-09-04T...",
  "updated_at": "2026-09-04T..."
}
```

### RunResponse
```json
{
  "run_id": "run_abc123def456",
  "case_id": 1,
  "status": "queued|running|succeeded|failed|cancelled",
  "current_stage": "detection|transport|...",
  "progress_percent": 45.0,
  "started_at": "...",
  "completed_at": null,
  "created_at": "...",
  "input_scene_ids": [],
  "metocean_data_ids": [],
  "configuration_snapshot": {},
  "model_version_ids": [],
  "provider_status": {},
  "outputs": null,
  "warnings": [],
  "error_details": null,
  "cancel_requested": false
}
```

### NoteResponse
```json
{
  "id": 1,
  "author_name": "Dr. Priya Sharma",
  "content": "Please review characterization",
  "is_supervisor_return": true,
  "created_at": "2026-09-04T..."
}
```
