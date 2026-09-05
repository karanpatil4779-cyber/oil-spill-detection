# IMPLEMENTATION_STATUS.md — Milestone 0: Repository Inspection & Gap Report

> **Status:** Draft, prepared for review before any code changes.
> **Generated:** 2026-09-04 against the repository at `c:\Users\karan\Desktop\SIH2026 OIL PROJECT` (HEAD commit of
> the *misconfigured* parent git repo is `8b5b66f`; see **Deviations D1** — this project's files are **not**
> tracked by git).
> **Rule honoured:** no scientific module, API route, database, or frontend file was modified during inspection.
> The only new file is this report. The only database write during testing was `users.last_login` from a
> successful login smoke test (a normal runtime side-effect).

---

## 1. Repository inventory (what exists)

```
apps/api/          FastAPI backend (main.py, auth.py, deps.py, routes/{auth,case,admin,analytics}_routes.py)
apps/db/           SQLAlchemy ORM (models.py) — 11 tables
apps/web/          React 18 + Vite 5 frontend (react-router, maplibre-gl, recharts)
engines/           Pure-Python science modules:
                     aging/        oil_age.py
                     ais/          gfw_client.py, behaviour.py, ais_filter.py
                     attribution/  ranker.py
                     characterization/  quantifier.py
                     detection/    sar_detector.py, eo_detector.py, s1_calibration.py, s1_georef.py,
                                   train.py (U-Net), prepare_dataset.py, run_sar_end_to_end.py
                     metocean/     prepare_incident_metocean.py, download_era5_case.py,
                                   download_cmems_{currents,incidents}.py, process_*.py, merge_incident_data.py
                     transport/    lagrangian_tracker.py
                     pipeline.py       6-stage orchestrator
data/            benchmarks/incidents.json, validation/origin_error_baseline.{json,csv},
                 processed/metocean/<5 incidents>/final_metocean.nc, raw/sar/jipro2018 (real detections),
                 raw/metocean/era5 + cmems
notebooks/       train_unet_colab.ipynb, validation_origin_error.ipynb
scripts/         seed_demo_data.py, freeze_validation_baseline.py, test_forward.py
tests/           test_e2e.py, test_transport.py, test_enhancements.py  (script-style, not pytest)
oil_spill.db     SQLite database (stale relative to models.py — see §4)
```

---

## 2. Exact tech stack & versions (as installed in `.venv`)

**Backend** (Python 3.14.2 via `.venv\Scripts\python.exe`)

| Package | Version |
|---|---|
| fastapi | 0.141.1 |
| uvicorn[standard] | 0.52.4 |
| SQLAlchemy | 2.0.52 |
| python-jose | 3.5.0 |
| passlib | 1.7.4 (+ bcrypt; logs `(trapped) error reading bcrypt version` — non-fatal) |
| numpy / pandas / scipy | 2.5.2 / 3.0.5 / 1.18.1 |
| xarray | 2026.7.0 |
| torch / torchvision | 2.13.0 / 0.28.0 |
| cdsapi / copernicusmarine | 0.7.7 / 2.4.1 |
| geopandas / shapely / pyproj / rasterio | 1.1.4 / 2.1.2 / 3.7.2 / 1.5.1 |
| requests / python-dotenv | 2.34.2 / present |

**Frontend** (Node v22.21.0, npm 10.9.4): react 18.3.1, react-dom 18.3.1, react-router-dom 6.30.6,
maplibre-gl 6.7.0, recharts 2.15.4, vite 5.4.21, @vitejs/plugin-react 4.3.4.

**Map:** `apps/web` uses **MapLibre GL + OpenFreeMap tiles (no API token required)**. `VITE_MAPBOX_TOKEN` is
**not referenced anywhere in `src`** (only in README) and no `apps/web/.env` exists. The Mapbox GL stylesheet
link in `index.html` is an unused/legacy leftover.

---

## 3. Exact startup / test / build commands — with actual recorded output

**Backend starts** (smoke test ran on port 8011 to avoid conflicts):
```
.venv\Scripts\python -m uvicorn apps.api.main:app --port 8011
  Uvicorn running on http://127.0.0.1:8011        <- startup OK
  GET /health -> {"status":"ok"}
  POST /auth/login (analyst@oilspill.gov/analyst123) -> 200, role=analyst
  GET /admin/users with analyst token -> 403 (server-side role enforcement CONFIRMED)
  GET /cases with analyst token -> 500 (sqlite3.OperationalError: no such column: cases.pipeline_status)
```
**Documented test scripts** (from project root):
- `.venv\Scripts\python tests\test_enhancements.py` → **ALL PASSED**
  (age estimation, real wind extraction `4.11 m/s`, forward forecast `centroid=[72.798 18.778] conf=0.96`,
  transit filter, ranker behavioural factor, EO import)
- `.venv\Scripts\python tests\test_transport.py` → **PASS** (72/100 particles active, origin `[72.8068, 19.0642]`)
- `.venv\Scripts\python tests\test_e2e.py` → **PASS (exit 0)** with notable data-source results:
  - metocean archive OK (u10 [-23.08,13.72] m/s, uo [-0.34,0.28] m/s)
  - Chitra backtracking 100/100 active → [72.7824, 19.0391]; Jipro 63/100 active
  - **GFW health check (presence dataset): PASS** — README's claim "key returns 401" is **outdated**
  - **GFW vessels/search (vessel-identity dataset): 403 Forbidden** — token lacks dataset permission (graceful)
  - CDSE auth: OK; **0 Sentinel-1 GRD products** found for Mumbai `2018-01-29..31` (window issue; CDSE search works)
- `npm run build` in `apps/web` → **success in 21.82s, 868 modules**; chunk-size warning (1.59 MB `index-*.js`)

**Test runner:** tests are **script-style** (do not require pytest, though `pytest` is installed). They are
invoked as scripts in README, and that is the supported path.

**Not run during inspection (side-effectful):** `scripts/freeze_validation_baseline.py` overwrites
`data/validation/origin_error_baseline.{json,csv}`; I reproduced its computation in a temp script instead (§10).

---

## 4. Database engine & schema (as it actually exists)

- Existing file: `oil_spill.db` (SQLite). `DATABASE_URL` in `.env` is set to an unreachable
  `postgresql://…@localhost:5432/oil_spill_db` (connection refused), so `apps/db/models.py` logs
  **“DATABASE_URL not reachable; falling back to SQLite”** and uses `sqlite:///oil_spill.db`.
- Tables present: `users, cases, case_notes, audit_log_entries, model_versions, data_source_configs,
  reports, incidents, detections, transport_results, attribution_results` (11 tables).
- **SCHEMA DRIFT (blocking defect):** the on-disk `cases` table is **missing `pipeline_status`**,
  which `models.py` and the case routes require. `Base.metadata.create_all()` does **not** add columns to an
  existing table and runs on every startup. Repro: `GET /cases` → `500 / sqlalchemy.exc.OperationalError:
  (sqlite3.OperationalError) no such column: cases.pipeline_status` (SELECT on `cases`). The same defect hits
  `GET /cases/{id}` and `POST /cases/{id}/run-pipeline` *given the current stale DB* (a fresh DB would build
  the correct schema).
- Auto-seeded users exist (admin/supervisor/analyst/analyst2, bcrypt-hashed) and login works.
- **No migrations system** (no Alembic): schema is created at startup only; nothing upgrades existing tables.

---

## 5. Current API routes (actual, verified from source + live smoke test)

Legacy (root router, **no auth**): `GET /`, `GET /health`, `POST /attribute/spill` (synchronous pipeline;
hangs on real data), `GET /sar/search`.

Auth: `POST /auth/login` → `{access_token, token_type, user{id,email,name,role}}`;
`GET /auth/me` → `{id,email,name,role,status}`. **No refresh-token endpoint exists.**

Cases (prefix `/cases`): `GET ""[?status_filter]`, `POST ""`, `GET /{id}`, `PATCH /{id}/status`,
`POST /{id}/run-pipeline`, `POST /{id}/rerun`, `GET /{id}/notes`, `POST /{id}/notes`,
`POST /{id}/return`, `POST /{id}/approve`, `POST /{id}/escalate`, `POST /{id}/override-rank`,
`POST /{id}/generate-report`, `GET /{id}/audit`.
(Note: `submit-for-review` is **not** a separate route; the frontend calls `PATCH /cases/{id}/status
{status:"pending_review"}` — that works.)

Admin (require_role("admin")): `GET|POST /admin/users`, `PATCH /admin/users/{id}`, `GET|PUT /admin/data-sources`,
`GET /admin/models`, `POST /admin/models/deploy`, `POST /admin/models/{id}/rollback`, `GET /admin/audit-log`.

Supervisor analytics (require supervisor/admin): `GET /analytics/throughput`, `/candidate-ratios`,
`/evidence-rate`, `/analyst-performance`.

**Not present (required for later milestones):** `POST /cases/{id}/runs`, `GET /runs/{run_id}`,
`GET /admin/system-status` (SystemDashboard uses hardcoded frontend constants), a report-export endpoint that
enforces supervisor approval, per-stage run/progress data, and configurable candidate-filter ratios.

**Response shapes:** `CaseResponse` wraps `pipeline_result` as an opaque JSON blob (nested pipeline fields
`detections, characterization, age, eo, forecast, suspects, sar_available, gfw_available, warnings,
origin_centroid, origin_bbox`). Role-aware: analyst sees only own cases (server-side IDOR guard on get_case);
supervisor sees all.

---

## 6. Current background-job capability

- **Requirement of the prompt:** none satisfied — **no queue library in `requirements.txt`** (checked:
  celery, rq, redis, dramatiq, huey, arq, dask.distributed, multiprocessing are absent).
- Existing mechanism: **FastAPI `BackgroundTasks`** in `run_pipeline_on_case`. Caveats in code: it blocks the
  single uvicorn worker while the heavy pipeline runs (so concurrent requests queue up), it has **no run_id /
  no progress / no stage tracking / no retries / no timeout guarantee**; `pipeline_status` is just
  `idle|running|done|error`; and the legacy `/attribute/spill` route runs synchronously, holding the HTTP
  request for the entire pipeline.
- This matches the reported "trigger hangs on real data" defect. Milestone 1 must add the smallest reliable
  worker (see Plan; documented choice in **Deviations D4**).


---

## 7. Environment variables & provider integrations (names only; values redacted)

`.env` keys present: `CDSE_USERNAME, CDSE_PASSWORD, CMEMS_USERNAME, CMEMS_PASSWORD, GFW_API_KEY,
ERA5_API_KEY, CDSAPI_RC, DATABASE_URL, DEBUG, API_VERSION, JWT_SECRET, JWT_ALGORITHM,
ACCESS_TOKEN_EXPIRE_MINUTES`. `.cdsapirc` exists. `apps/web/.env` does **not** exist (no frontend env needed —
see §2 map note).

Checked validity (live, 2026-09-04):
| Provider | Endpoint/Key | Actual result |
|---|---|---|
| Copernicus Data Space (CDSE) | `CDSE_USERNAME/PASSWORD` | **Valid** — token issued, product search returned 200 (0 matches in the tested narrow window) |
| Global Fishing Watch | `GFW_API_KEY` | **Authenticated + presence dataset OK** (health check PASS) — but **403 on vessel-identity dataset** (`/vessels/search`, `/vessels/{id}`); README's "returns 401" claim is outdated |
| ERA5 / CDS | `.cdsapirc` | File present; live end-to-end call not re-made (data already pre-processed in repo) |
| CMEMS | `CMEMS_USERNAME/PASSWORD` | Credentials present; live call not re-made (pre-processed currents committed) |
| Postgres | `DATABASE_URL` | **Unreachable** (localhost:5432 refused) → app uses SQLite fallback |
| Mapbox | `VITE_MAPBOX_TOKEN` | **Not set and not needed** (MapLibre/OpenFreeMap) |

---

## 8. Authentication & role enforcement (server-side, confirmed)

- Login: bcrypt verify via passlib; JWT (HS256) with `sub`=user id + `role` claim; expiry 480 min by default.
  Authorization **never trusts the token `role` alone** — `deps.require_role` reloads the user from DB and
  checks row `role` + `status`.
- Confirmed live: analyst token + `GET /admin/users` → **403**. Admin/supervisor role deps are wired on
  admin + supervisor routes.
- IDOR: analyst queries are scoped to `Case.analyst_id` on `GET /cases` and `GET /cases/{id}` (403 for other
  analysts). Notes/audit endpoints currently let any authenticated user read any case's audit/notes
  (tighten in Milestone 6/7).
- **Security gaps found (input to Milestone 10, preserved here):** hard-coded dev `JWT_SECRET` fallback in
  `auth.py`; no refresh-token rotation; no rate limiting; no request-body schema on legacy routes; CORS
  restricted to `localhost:5173 / 127.0.0.1:5173`; `PATCH /cases/{id}/status` lets **admin bypass** the
  analyst/supervisor transition matrix (`current_user.role != "admin"` step); `generate-report` callable by
  any authenticated user on **any status** (approval gate missing); login page shows demo credentials openly;
  seeded users auto-created on first startup, not gated behind explicit demo mode.
---

## 9. Scientific modules — status against the baseline table (all checks read-only)

| Baseline-claimed module | Actual path | Status | Evidence |
|---|---|---|---|
| `detection/sar_detector.py` Sentinel-1 retrieval + CFAR | `engines/detection/sar_detector.py` | **working** | CDSE auth OK; real output exists (`data/raw/sar/mt_jipro_neftis_mumbai_2018/detections.json` — 84 dark-spot candidates, mean contrast ≈ −14 dB) |
| U-Net training notebook + checkpoint | `notebooks/train_unet_colab.ipynb` + `engines/detection/train.py` | **needs hardening** | Code + notebook present; **`engines/detection/models/` is empty — no checkpoint committed**; `run_sar_end_to_end.load_unet()` falls back to CFAR when absent |
| `detection/eo_detector.py` Sentinel-2 NDHI | `engines/detection/eo_detector.py` | **working** (importable/wired) | Import test passes; used in `pipeline._run_eo_detection`; full run not exercised (S2 scene availability dependent) |
| `detection/s1_calibration.py` sigma0 from annotation XML | `engines/detection/s1_calibration.py` | **working** | Pure parser; used by SAR detection path |
| `detection/s1_georef.py` pixel→geo mapping | `engines/detection/s1_georef.py` | **working** | Pure parser + `GeolocGrid` bilinear mapping |
| `characterization/quantifier.py` area/volume/tonne + NOAA thickness | `engines/characterization/quantifier.py` | **working** | Unit-verified; volume uses 1 µm default film thickness |
| `metocean/` ERA5+CMEMS acquisition/merge/process | `engines/metocean/` | **working** | 6 processed archives; `test_e2e` verified u10/v10/uo/vo; each incident has its own `final_metocean.nc` |
| `transport/lagrangian_tracker.py` backward+forward | `engines/transport/lagrangian_tracker.py` | **working** | `track_backward` + `forecast_ensemble` verified; validation reproduced (§10) |
| `aging/oil_age.py` SAR-contrast + wind age | `engines/aging/oil_age.py` | **working** | Interval `age_min_hours…age_max_hours` + confidence returned; wind extraction from real NetCDF (4.11 m/s in test); **UI lacks last-clean-scene / observation-gap / assumptions view** |
| `ais/gfw_client.py` GFW v3, registry, presence | `engines/ais/gfw_client.py` | **working** (primary), **needs hardening** | Presence endpoint PASS live; identity dataset 403 (graceful); no caching/retry/backoff |
| `ais/behaviour.py` loitering/stationary/turnaround | `engines/ais/behaviour.py` | **working** | Unit-tested (transit filter, anomaly scores) |
| `ais/ais_filter.py` space/time filter | `engines/ais/ais_filter.py` | **needs hardening** | Legacy file with `_get_mock_matches()` that **fabricates suspects** — currently **not wired into pipeline** (must stay unwired); space/time filtering only, no trajectory/quality checks |
| `attribution/ranker.py` proximity 35 / cargo 30 / duration 20 / behaviour 15 | `engines/attribution/ranker.py` | **working** | Defaults confirmed in code (`__init__` weights); per-vessel factor breakdown computed |
| `pipeline.py` 6-stage orchestration | `engines/pipeline.py` | **working** (blocked at HTTP layer) | All stages callable; `status`/`warnings`/`sar_available`/`gfw_available` returned; `run_sar=False` default avoids 1.7 GB SAR downloads |

### Frontend integration status (same vocabulary)

| Frontend asset | Status | Notes |
|---|---|---|
| 8 workspace panels + OilMap + mapFeatures | **needs integration** | `Panel3OriginHindcast` references an **undeclared variable `age`** (line 52) → `ReferenceError` crash when rendering a case with results; `Panel5AISVessels` hardcodes **`totalInRegion = 1847`** (fabricated "vessels in region" — constraint 3 violation); `Panel1` "look-alike" is a naive confidence threshold, not an uncertainty-engine output; age panel doesn't show last-clean-scene/observation-gap/assumptions; no per-stage success/insufficient-evidence gating (renders partial data) |
| Admin pages | **needs hardening** | `SystemDashboard` renders **hardcoded mock** feed status + job counts with no API backing and no `DEMO DATA` label (constraint 3 violation). `UserManagement`, `ModelRegistry`, `DataSourceConfig`, `AuditLog` are wired to real APIs |
| ProtectedRoute/layouts | working | Route guards mirror server roles; these are UX mirrors only — server enforces |
| LoginPage | **needs hardening** | Demo credentials displayed in plain sight; no explicit demo-mode gate |
| Build | working | `vite build` succeeds (21.82s) |
---

## 10. Validation metrics — reproduction (no files overwritten)

The prompt's recorded baseline (from `data/validation/origin_error_baseline.json`):
**mean 26.24 km, median 21.1 km, RMSE 30.87 km** (n=5, seed=42, 24 h, 100 particles).

Reproduced (temp script mirroring `scripts/freeze_validation_baseline.py` exactly: per-incident `np.random.seed(42)`,
`detection_time = "YYYY-MM-DDT00:00:00"`, `duration_hours=24`, `num_particles=100`):

| Incident | Recorded | Reproduced | Match |
|---|---|---|---|
| msc_chitra_khalijia3_mumbai_2010 | 16.66 km | 16.66 km | ✅ exact |
| mt_jipro_neftis_mumbai_2018 | 21.10 km (60 active) | 17.22 km (62 active) | ⚠ differs |
| gal_constructor_mumbai_2021 | 34.26 km | 34.26 km | ✅ exact |
| ennore_chennai_coastal_2017 | 53.23 km | 53.23 km | ✅ exact |
| kandla_gulf_kutch_2023 | 5.93 km | 5.93 km | ✅ exact |
| **Aggregate** | **26.24 / 21.1 / 30.87** | **25.46 / 17.22 / 30.39** | ⚠ see below |

**Discrepancy explanation (no tuning):** 4/5 incidents reproduce bit-for-bit; only MT Jipro Neftis differs
(17.22 km / 62 active vs recorded 21.10 km / 60 active). The per-particle loop exits when a particle leaves
the forcing domain, so the exact random-walk/diffusion sequence consumed depends on xarray nearest-neighbour
selection and numpy RNG state across versions. The recorded baseline was frozen on an earlier numpy/xarray
environment; the small active-set difference (62 vs 60) shifts the median from 21.1 to 17.22. I have **not**
changed the recorded baseline; both sets are reported and the discrepancy is reproducible, not an improvement.

---

## 11. Failing or hanging workflows (exact repro steps)

1. **`GET /cases` → 500 (schema drift).** Start uvicorn; `POST /auth/login` (any seeded user);
   `GET /cases` → `500 sqlite3.OperationalError: no such column: cases.pipeline_status`.
   Root cause: existing `oil_spill.db` `cases` table predates the `pipeline_status` column; `create_all()`
   never alters existing tables. Affects `GET /cases`, `GET /cases/{id}`, `POST /cases/{id}/run-pipeline`.
2. **Pipeline trigger hangs on real data.** `POST /cases/{id}/run-pipeline` uses FastAPI `BackgroundTasks`:
   no `run_id`, no progress/stage, no timeout/retry; blocks the single uvicorn worker during the run.
   Legacy `POST /attribute/spill` runs synchronously and holds the HTTP request for the whole pipeline
   (minutes on real metocean/transport; tens of minutes with SAR downloads). Repro: create a case with
   `run_sar` defaults and observe the request/worker blocking and the frontend polling `pipeline_status`
   with no stage feedback.
3. **Frontend workspace crash.** `Panel3OriginHindcast.jsx` line 52 references the undeclared variable
   `age` (`age?.age_hours != null`); rendering a case with a pipeline result throws `ReferenceError` and
   blanks the workspace.
4. **Fabricated numbers presented as real (constraint 3).** Admin `SystemDashboard.jsx` (PIPELINES/JOBS
   constants with fake "last sync", "87% quota", job counts) and `Panel5AISVessels.jsx`
   (`totalInRegion = 1847`) render fabricated figures with no `DEMO DATA` label and no API backing.
5. **GFW identity dataset 403.** `GET /vessels/search` / `/vessels/{id}` → 403 (token lacks the
   vessel-identity dataset permission); the primary presence path works and the pipeline degrades gracefully.
   README's "401" claim is outdated and should be corrected.
6. **U-Net checkpoint absent.** `engines/detection/models/` is empty; `load_unet()` falls back to CFAR.
   Model-version registry has nothing to register for the trained model.

---

## 12. Files that must change vs. files that must remain untouched

**Must remain untouched (scientific logic / committed evidence):**
- `engines/detection/sar_detector.py`, `s1_calibration.py`, `s1_georef.py`, `eo_detector.py` (science)
- `engines/characterization/quantifier.py`, `engines/transport/lagrangian_tracker.py`,
  `engines/aging/oil_age.py`, `engines/ais/gfw_client.py`, `engines/ais/behaviour.py`,
  `engines/attribution/ranker.py`, `engines/pipeline.py` (orchestrator logic — integration only)
- `data/benchmarks/incidents.json`, `data/validation/origin_error_baseline.{json,csv}`,
  `data/raw/sar/mt_jipro_neftis_mumbai_2018/` (real detections), `notebooks/validation_origin_error.ipynb`

**Must change (integration / hardening):**
- `apps/api/routes/case_routes.py` (async runs; remove BackgroundTasks-only behaviour), new `runs` routes,
  `apps/db/models.py` (Run/PipelineRun + migrations), `apps/api/routes/admin_routes.py` (system-status API;
  create-admin confirmation; model registry wiring), `apps/api/routes/analytics_routes.py` (candidate-ratio
  metrics), `apps/api/auth.py`/`deps.py` (security items: secret, refresh, rate limiting), `apps/api/main.py`
  (startup seeding gating + demo mode)
- `apps/web/src/components/workspace/Panel3OriginHindcast.jsx` (crash fix), `Panel5AISVessels.jsx`
  (remove hardcoded 1847; wire real ratio), `pages/admin/SystemDashboard.jsx` (wire to real API or mark
  `DEMO DATA`), `Workspace.jsx` (run progress UI), `pages/analyst/NewInvestigation.jsx`, `api/client.js`
- `scripts/seed_demo_data.py`, `tests/` (pytest suite), `README.md`, new `API_CONTRACT.md`, new
  `IMPLEMENTATION_STATUS.md` (this file)
---

## 13. Deviations (repository reality vs. this prompt)

- **D1 — Git is not tracking this project.** `git rev-parse --show-toplevel` → `C:/Users/karan`; the remote is
  `monastery360-sikkim` (an unrelated repository). None of the oil-spill files are tracked; the parent repo's
  working tree is the entire Desktop. I will not "commit" milestones with git unless an explicit repo is
  created. All milestone verification therefore uses file/diff checks + live tests.
- **D2 — Baseline-table path names differ.** Modules live under `engines/…` (not `detection/…`), U-Net
  notebook at `notebooks/train_unet_colab.ipynb` (not `detection/detection_and_train_unet_colab.ipynb`).
- **D3 — "U-Net checkpoint exists" is false.** `engines/detection/models/` is empty; training code exists but
  no weights are present. Pipeline falls back to CFAR. Flagged as `needs hardening`, not silently fixed.
- **D4 — No queue library exists.** Milestone 1 therefore uses the prompt's fallback option: the smallest
  reliable worker compatible with the current stack. Proposed choice (to confirm after Milestone 0 review):
  a long-lived in-process job runner using a DB-backed `runs` table + a watchdog thread pool (no
  Redis/RabbitMQ dependency, keeps the SQLite/local demo runnable); state
  `queued → running → succeeded | failed | cancelled`; exponential backoff retries for providers with
  explicit limits stated.
- **D5 — Reported GFW "401" is outdated.** Live test shows the token authenticates and the presence dataset
  works (health check PASS); only the vessel-identity dataset returns 403 (permission). README to be updated;
  no fabrication was substituted.
- **D6 — Validation metrics differ for one case.** Reproduced aggregate 25.46 / 17.22 / 30.39 vs recorded
  26.24 / 21.1 / 30.87; 4/5 incidents bit-exact; MT Jipro differs (62 vs 60 active particles) explained in §10.
- **D7 — Postgres is configured but not running**; the app falls back to SQLite by design. Documented; no
  schema change was made.
- **D8 — `ais/ais_filter.py` contains a mock-suspect fallback** (`_get_mock_matches`). It is not wired into
  the pipeline; it must never be. Flagged `needs hardening` and excluded from production paths.
- **D9 — Existing DB is stale** (`cases.pipeline_status` missing) — see §4/§11. Requires a rebuild or a real
  migration step in Milestone 1 before the API can run end-to-end.
- **D10 — Metrics/claims reproduced honestly.** Where my reproduction differs from recorded numbers (§10) both
  are reported; no numbers were invented or "improved".
---

## 14. Consolidated status table + prioritized implementation plan

### 14.1 Status (exact values: `working` · `needs integration` · `needs hardening` · `blocked` · `not present`)

| # | Component | Status |
|---|---|---|
| 1 | engines/detection/sar_detector.py (CDSE + CFAR) | working |
| 2 | engines/detection/eo_detector.py (S2 NDHI) | working |
| 3 | engines/detection/s1_calibration.py / s1_georef.py | working |
| 4 | engines/detection/train.py + notebook (U-Net) | needs hardening (no checkpoint) |
| 5 | engines/characterization/quantifier.py | working |
| 6 | engines/metocean/ (ERA5 + CMEMS archive) | working |
| 7 | engines/transport/lagrangian_tracker.py (backward + forward) | working |
| 8 | engines/aging/oil_age.py (interval + confidence) | working |
| 9 | engines/ais/gfw_client.py | working (identity dataset needs hardening) |
| 10 | engines/ais/behaviour.py | working |
| 11 | engines/ais/ais_filter.py | needs hardening (mock fallback, unwired) |
| 12 | engines/attribution/ranker.py | working |
| 13 | engines/pipeline.py | working |
| 14 | API auth + role middleware | working (hardening items in §8) |
| 15 | API case CRUD + status flows | blocked (DB schema drift) |
| 16 | Async pipeline execution / `/runs` endpoints | not present |
| 17 | Legacy `/attribute/spill` (sync) | blocked for real data (hangs) |
| 18 | Per-stage structured results + no-partial UI rendering | not present |
| 19 | Age/uncertainty/look-alike + decision labels | needs integration |
| 20 | Forward-forecast / origin-region multi-scenario UI | needs integration |
| 21 | AIS space-time-trajectory-quality filtering + fallback | needs integration |
| 22 | Candidate-reduction ratio (real) | not present (hardcoded 1847 in UI) |
| 23 | Supervisor analytics | working (basic) |
| 24 | Admin system-status API | not present (mock UI) |
| 25 | Role-separated product workflow + auth tests | needs hardening |
| 26 | Report export gated by approval | not present |
| 27 | Audit immutability / model-version reproducibility | needs hardening |
| 28 | Test suite (pytest-style, auth boundaries, async) | needs hardening |
| 29 | Demo mode (explicit gate, labeled data) | not present |
| 30 | Security review items (secrets, rate limit, CORS, validation) | needs hardening |
| 31 | README / API_CONTRACT / run-command docs | needs hardening (README partially outdated) |

### 14.2 Prioritized implementation plan (for review before Milestone 1)

1. **P0 — Unblock the app (first Milestone-1 sub-checkpoint).** Rebuild/migrate the DB schema
   (`pipeline_status` and any new `runs` tables), keep SQLite/dev path working. Verify `GET /cases` returns 200.
2. **P1 — Async pipeline execution (Milestone 1).** DB-backed `runs` table; `POST /cases/{id}/runs` → 202 with
   `run_id`; `GET /runs/{id}` with status/progress/current_stage/warnings/errors/timestamps; provider retries +
   exponential backoff + timeouts; guaranteed transition away from `running`; frontend polling UI + failure
   state. Replace BackgroundTasks usage with the worker runner; keep legacy routes working but routed through
   the runner so nothing blocks the HTTP worker.
3. **P2 — Wire scientific stages to runs (Milestone 2).** Each stage returns structured result
   (`data, status…`) per the repo's `PipelineOutput` naming; the frontend only renders a stage after it
   succeeded or explicitly returned insufficient evidence; fix the `Panel3` crash and remove fabricated UI
   numbers (1847; admin SYSTEM dashboard) or tag them `DEMO DATA`.
4. **P3 — Age, uncertainty, look-alike (Milestone 3).** Expose `time_since_first_observation` +
   `estimated_time_since_release` (interval + confidence) with last-clean-scene/first-detected scene/gap/
   assumptions; emit final decision labels (exact strings); uncertainty layer flags unavailable signals.
5. **P4 — Forecast + origin region (Milestone 4).** Backward result as origin region/ellipse + time window;
   multi-scenario when age interval is wide; forward spread cone + horizon + forcing + transport confidence.
6. **P5 — AIS filtering + fallback (Milestone 5).** Space/time/trajectory/quality filtering using
   `gfw_client`+`behaviour` (as-is); independent-evidence fallback path with labelled adapters;
   candidate-reduction ratio from real counts; cautious labels (`candidate source vessel` etc.).
7. **P6 — Role-separated workflow tests (Milestone 6).** Server-side "must not" enforcement for
   analyst/supervisor/admin; mandatory return note; creating-admin confirmation; demo-flag gating of seeded
   users; authorization tests that actually run.
8. **P7 — API contract + reports + audit (Milestones 7–8).** `API_CONTRACT.md`; approval-gated export;
   immutable audit (append-only DB + hash chain or equivalent); model-version/run snapshots.
9. **P8 — Testing + validation (Milestone 9).** pytest suite per the milestone checklist; rerun the 5-incident
   validation and record actual metrics (§10 values above are the current reproduction).
10. **P9 — Performance/security/demo readiness (Milestone 10).** SAR scene-discovery/caching/resumable
    downloads + job progress; security findings list with severities; demo mode; README refresh.

**Stop — this plan is presented for review before any code change. Milestone 1 starts only after scope
confirmation.**