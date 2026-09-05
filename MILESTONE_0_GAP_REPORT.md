# Milestone 0 — Repository Inspection and Gap Report

**Date:** 2026-09-05
**Scope:** Verification pass before frontend work. No repository code was modified.
**Method:** Static source analysis. See "Verification limits" — the sandbox could not execute the stack.

> Written as a new file rather than overwriting the existing `IMPLEMENTATION_STATUS.md`, so no prior content is lost. Merge or supersede as you prefer.

---

## Headline

The frontend is **not** the main gap. It is functionally wired, has all 8 workspace panels, and correct routing. The problem is upstream: **several numbers the frontend displays are wrong, fabricated, or mean something different from what their field name says.** Making the UI beautiful without fixing these would produce a more convincing wrong answer, which is the specific failure mode the master prompt's non-negotiable constraints exist to prevent.

Three findings would embarrass the project under judge questioning:

1. **`est_volume_tonnes` is overstated ~1000×** — it is kilograms. A ~10 tonne slick renders as `10416.0` tonnes.
2. **The headline verdict "Likely oil spill" does not measure oil.** It is thresholded from `overall_confidence`, which is the mean of an age-confidence ladder of magic constants and *the fraction of transport particles that stayed inside the NetCDF domain*.
3. **Admin can read full investigation content**, defeating the platform's central RBAC claim, via `GET /cases/{id}/runs` → `outputs`, which is byte-identical to `pipeline_result`.

---

## Verification limits (read this before trusting any "verified" below)

| Capability | Status |
|---|---|
| Run FastAPI backend | **Blocked** — PyPI returns proxy 403; fastapi/sqlalchemy uninstallable. System python3 has only numpy + pandas. |
| Run `npm run build` | **Blocked** — npm registry 403, and `node_modules` holds Windows binaries (`@rollup/rollup-linux-x64-gnu` missing). |
| Run `pytest` | **Blocked** — pytest not installed, cannot install. |
| Read all source | Done |
| Recompute validation aggregates | Done (numpy/pandas present) |
| Query `oil_spill.db` | Done (sqlite3 stdlib) |

Everything marked **verified** below is verified *against source or the live SQLite DB*. Anything requiring execution is marked **needs your run**. Per the prompt's "never fabricate a metric" constraint, I have not filled these in with plausible values.

**Commands for you to run on Windows and paste back:**
```
.venv\Scripts\activate
python -m uvicorn apps.api.main:app --port 8000      # capture full startup log
python -m pytest tests/test_platform.py -v            # 42 tests claimed
cd apps\web && npm run build
```

---

## Tech stack (verified)

**Backend:** FastAPI + SQLAlchemy, Python 3.14 (`__pycache__` shows `cpython-314`). JWT via python-jose, passlib/bcrypt. In-process `ThreadPoolExecutor` job runner — no Redis/Celery.
**Frontend:** React 18.3.1, Vite 5.4.10, react-router-dom 6.30.6, **maplibre-gl 6.7.0**, recharts 2.15.4. 35 files, ~2,900 lines. Plain CSS, 427 lines, no design system.
**DB:** SQLite at `oil_spill.db` — **note `.env` requests PostgreSQL** and it silently falls back (see D15).

**Live DB contents:** 7 cases, 1 run, 41 attribution_results, 2 transport_results, 12 audit entries, 4 users, **0 detections, 0 model_versions, 0 reports**.

---

## Status of each module in the prompt's baseline table

Status values per the prompt: `working` / `needs integration` / `needs hardening` / `blocked` / `not present`.

| Module | Prompt claim | Actual | Note |
|---|---|---|---|
| `detection/sar_detector.py` | Working | **needs your run** | Source is coherent; cannot execute (no rasterio). |
| `detection/*_unet_colab.ipynb` | Training code + checkpoint | **not present** (checkpoint) | `engines/detection/models/` is empty. No U-Net inference path exists anywhere in `pipeline.py`. All "CFAR/U-Net agreement" UI is therefore unbackable. |
| `detection/eo_detector.py` | Working | **needs hardening** | `confirmed` = `oil_mask.any()` — one pixel. `wgs84: true` is a hardcoded literal emitted even when reprojection failed. |
| `detection/s1_calibration.py` | Working | **needs your run** | Not executable here. |
| `detection/s1_georef.py` | Working | **needs your run** | Not executable here. |
| `characterization/quantifier.py` | Working | **needs hardening — 3 unit/method defects** | tonnes-vs-kg (D-S1); area from bbox not `area_px` (D-S3); 40 m pixel constant vs 10 m native (D-S4). |
| `metocean/` | Working, 6 datasets | **working** | 6 processed incident dirs confirmed on disk. |
| `transport/lagrangian_tracker.py` | Working, ~26 km | **working, aggregates reproduce** | See metrics section. `track_forward` is dead code; forward path runs via `forecast_ensemble`. |
| `aging/oil_age.py` | Working | **needs hardening** | Interval is a fixed % of the estimate; `frames_used` is miscounted (D-S5). |
| `ais/gfw_client.py` | Working, key may need refresh | **needs hardening** | Client itself is well written with a good error message — which `pipeline.py` then discards (D-S2). |
| `ais/behaviour.py` | Working | **working** | |
| `attribution/ranker.py` | Working, 35/30/20/15 | **weights confirmed; input poisoned** | Weights verified. But `proximity` (35%) can be maximised by a fabricated position (D-S2). |
| `pipeline.py` | Six-stage orchestration | **needs hardening** | Orchestration works; it is where most honesty defects live. |

---

## Validation metrics

**Recomputed from `data/validation/origin_error_baseline.csv` (5 incidents):**

| Metric | Prompt baseline | My recomputation | Match |
|---|---|---|---|
| Mean | 26.2 km | **26.2360 km** | yes |
| Median | 21.1 km | **21.1000 km** | yes |
| RMSE | 30.87 km | **30.8711 km** | yes |

Independent geodesic check: all 5 `origin_error_km` values agree with a haversine recomputation from their own `source_lon/lat` → `origin_lon/lat` pairs to within **0.01 km**. The frozen baseline is internally sound.

**Discrepancy to resolve:** `README.md:92-99` claims a *re-run* on 2026-09-04 produced mean 25.46 / median 17.22 / RMSE 30.39, attributing the difference to numpy/xarray RNG state. This is consistent with a real cause — `lagrangian_tracker.py` seeds no RNG anywhere, so **identical inputs produce different origins between runs**. That is a reproducibility problem for a forensic tool independent of the metric question. I could not re-run the model (no xarray/scipy). **Needs your run.**

---

## Critical defects

### Backend / authorization

| ID | Sev | Defect |
|---|---|---|
| **D3** | **Critical** | **Admin investigation-data isolation is defeated.** The 403 block exists only on `GET /cases/{case_id}` (`case_routes.py:309`). `GET /cases/{id}/runs` explicitly admits admin (`:189`) and returns `outputs`, which `runner.py:307` and `:312` write as the *same object* as `pipeline_result` — confirmed byte-identical in the live DB (both 31,088 chars for case 6). Admin also reads notes (`:496`), case audit incl. override justifications (`:671`), can **write** notes (`:521`), and can call `generate-report` (`:635`). Directly contradicts the Milestone 6 requirement and `README.md:123`. |
| **D2** | **Critical** | **IDOR:** `PATCH /cases/{case_id}/status` (`case_routes.py:451-484`) never compares `analyst_id`. Any analyst can drive any other analyst's case to `pending_review`/`closed`/`insufficient_evidence`. Every other analyst route has the check. |
| **D1** | **Critical** | **`POST /cases/{id}/run-pipeline` can never succeed.** `_extract_confidence` (`case_routes.py:687-694`) does `result.get("age", {})` — the key *exists* with value `None`, so the default never applies → `AttributeError` on `.get`. Raised at `:404` before `commit()` at `:407`, so `pipeline_result` is never persisted and the case always lands `error`. `runner.py:343` has the correct `result.get("age") or {}` — the two copies diverged. Corroborated: only case 6 (the `/runs` path) has real data. |
| **D4** | **Critical** | **JWT secret is the in-source default.** `auth.py:13` fallback literal is byte-identical to `.env`'s `JWT_SECRET`. Anyone reading tracked source can forge an admin token. |
| **D5** | **Critical** | `POST /attribute/spill` and `GET /sar/search` are **unauthenticated and synchronous** (`main.py:89,137`) — any anonymous caller triggers provider downloads on the HTTP worker. |
| **D6** | High | Unreachable code sold as a control: `admin_routes.py:115` `current_user.role != "admin"` is unsatisfiable under `Depends(require_role("admin"))` at `:109`. `API_CONTRACT.md:153` documents it as enforced. **No admin-creation confirmation step exists.** Role strings are never validated against an allowlist. |
| **D7** | High | `GET /admin/system-status` provider statuses are **literals** (`admin_routes.py:333-338`). `API_CONTRACT.md:199` claims "from startup checks"; no startup check exists. `health_check()` exists on both detectors and is never called. |
| **D8** | High | `scripts/seed_demo_data.py` writes a hand-authored blob into case 1 with `overall_confidence = 0.72` hardcoded and `status: "completed"` (a value the pipeline never emits) — **no `is_demo` flag**. This is the record currently in `pending_review`. |
| **D9/D10/D17** | High | `override-rank`, `rerun`, and `escalate` are **no-ops that return success messages**. `rerun` returns `"Re-run of {stage} queued"` and queues nothing. |
| **D11** | High | Orphaned `queued` runs deadlock a case forever: watchdog filters `status=="running"` AND `started_at < deadline`, but `started_at` is NULL when queued (`runner.py:385-388`), and `case_routes.py:153` then 409s every new run. No API to clear. |
| **D15** | Medium | Silent Postgres→SQLite downgrade on connect failure, warning only (`models.py:43-50`). |
| **D18** | Medium | `age_hours` can be `NaN`, which Python's `json` emits as bare `NaN` — **invalid JSON, `JSON.parse` throws in the browser.** Reachable via `/runs` with `run_sar=True`. |

Also: report generation is **approval-gated correctly** (`case_routes.py:645`, verified) — but **no export exists at all.** No `FileResponse`/`StreamingResponse` in `apps/api/`, no PDF library in `requirements.txt`. `pdf_path` is a fabricated string; no file is written.

Async runner (verified): threads, concurrency **2**, **3 total attempts**, backoff 1.0s→2.0s, watchdog deadline **3600s**, poll **10s**. A failed download cannot leave a run stuck in `running` (atomic transition at `runner.py:170-178`, plus two fallback layers) — **but in practice it never reaches the runner**: `pipeline.py:85` swallows it, so the run ends **`succeeded`** with a warning.

### Scientific honesty (these are the ones that matter for a demo)

| ID | Sev | Defect | What a judge would wrongly believe |
|---|---|---|---|
| **D-S1** | **Critical** | `quantifier.py:122` — `est_volume_tonnes = vol_m3 * oil_density`. Density is kg/m³, so the value is **kilograms**. Missing `/1000`. | "~10,000 tonnes spilled" (major disaster) instead of ~10 tonnes. |
| **D-S2** | **Critical** | `pipeline.py:224-225` — when GFW returns no mean position, the vessel is placed at **the centre of the search box**, which is ≈ the origin centroid. `ranker.py:89-93` then gives it `proximity ≈ 1.0`, the max, on the **heaviest factor (35%)**. | "This ship was right at the spill origin." Reality: we never knew where it was. |
| **D-S6** | **Critical** | `gfw_available` is set `True` at `pipeline.py:170` *before any HTTP call*, and a 403 is caught at `:232` with a stderr log only — **nothing appended to `warnings`**. `suspects: []` + `gfw_available: true` is emitted. | "AIS coverage was good and no vessels were near the origin" — an *exculpatory* finding produced by an auth error. Same latent flaw for `sar_available` at `:75`. |
| **D-S7** | **Critical** | `overall_confidence` = mean of the age ladder and `forecast.confidence`, the **fraction of particles that stayed in the NetCDF domain**. Thresholded into the verdict at `Panel1Detection.jsx:102`. **Nothing in this chain measures whether the target is oil.** | "The system assessed this as 78% likely to be oil." |
| **D-S8** | High | `lagrangian_tracker.py:60-62, 77-78` — on current/wind extraction failure, velocity is set to `0.0` rather than deactivating the particle. The `np.isnan` guard at `:116` never fires. Frozen particles still count toward `origin_centroid`, `origin_bbox`, and `forecast.confidence`. | Origin biased toward the detection point; the confidence number is inflated by dead particles. |
| **D-S9** | High | `likely_oil_type` is **always** the literal `"crude_oil"` (`quantifier.py:80`, called with empty kwargs at `pipeline.py:93`). Film thickness is hardcoded 1 µm — the module's own docstring gives the plausible range as 0.04–3000 µm. | "The system classified the oil type from its film-thickness signature." |
| **D-S5** | High | `pipeline.py:105` passes `frames=len(detections)` where the contract is *number of SAR scenes* (`oil_age.py:125`). More dark spots in one image ⇒ `confidence += 0.3` **and** skips the ±70% single-scene widening. `method` is a constant string claiming `multi_pass` which never runs. | "Age was cross-checked across multiple satellite passes." One scene. |
| **D-S3/S4** | High | Area is computed from **bounding boxes** (`quantifier.py:101`) while the true component area sits unused in `det["area_px"]`; and `spatial_resolution_m` defaults to **40 m** against 10 m native IW GRD (16× overstatement). Compounds with D-S1 to ~10⁴. | "Measured slick area." |
| **D-S10** | High | No RNG seed anywhere in the integrators (`:125,171,226`), and `diffusion_sigma=0.01` is applied in **degrees after** the m→deg conversion — a flat ~1.1 km/h random walk unrelated to the eddy field, accumulating to ~±7.7 km over 48 h. It **dominates** `origin_bbox` and `spread_deg`. | The displayed origin region size is mostly an artefact of one constant, and re-runs disagree. |
| **D-S11** | Medium | `ais_filter.py:88-107` returns fabricated vessels `"Suspect Tanker A"` / `"Cargo Ship B"` at the bbox centre on a `logger.warning`. Currently **unreachable** (no caller) but imports cleanly and matches the suspect schema. Recommend deletion. | — |
| **D-S12** | Medium | `origin.std_dev` **is computed** (`lagrangian_tracker.py:267`) and then discarded by `pipeline.py:300-301`. Origin uncertainty is available for free. | — |

**Likely-pervasive, needs your run:** `oil_age.py:141` treats `mean_db` as a water-relative contrast, but `sar_detector.py:408` stores **absolute** dB backscatter. Open-water VV ≈ −20 dB → `contrast_db = +20` → `abs()` exceeds `MAX_CONTRAST_DB=15` → `_contrast_to_age` returns the hardcoded `3.0` (`oil_age.py:102`). **Age may be pinned near 3 h on essentially every real scene.** Confirm by running `detect_from_product` on a real GRD and printing the `mean_db` distribution.

### Frontend

| ID | Sev | Defect |
|---|---|---|
| **D-F1** | **Critical** | **Live crash.** `Panel1Detection.jsx:109-116` — `computeLookalikeRisk(confidence)` references `data` at line 114, which is not a parameter (called with one arg at `:16`). Throws `ReferenceError: data is not defined` whenever `risk >= 0.25`, i.e. whenever confidence < 0.75. Given D-S7 this is the common path. |
| **D-F2** | **Critical** | Look-alike risk is defined as `1 - confidence` — not an independent assessment, just a restatement of D-S7's number, presented as a distinct evidence axis. |
| **D-F3** | High | Vessel labels are assigned **positionally**: `Panel6Attribution.jsx:72` — `isTop ? "Probable source vessel" : "Candidate source vessel"`. Rank 1 is always "probable" regardless of score. `"insufficient evidence"` is never emitted. |
| **D-F4** | High | The four decision-label strings exist **only in the frontend**, duplicated in `Panel1Detection.jsx:102-106` and `Panel7DataQuality.jsx:117-120`, computed from a number no engine produces. For any direct `/attribute/spill` call `overall_confidence` is `undefined` → `|| 0` → **"Likely false detection" for every run.** |
| **D-F5** | High | `Panel5AISVessels.jsx:100`'s "AIS unavailable" branch is gated on `gfw_available` being false — which per D-S6 never happens. **The fallback message is unreachable.** |
| **D-F6** | Medium | `index.html:8` loads **Mapbox** GL CSS from `api.mapbox.com` while the app uses **maplibre-gl**. Wrong stylesheet; MapLibre's own CSS is never loaded, so controls/popups are unstyled. |
| **D-F7** | Medium | No `ErrorBoundary` anywhere. Any panel throw (see D-F1, D18) blanks the whole workspace. |
| **D-F8** | Medium | Cannot distinguish "stage not requested" from "stage failed" from "no data" — all three are `null`. `provider_status`/`warnings`/`error_details` live on the `Run`, not in `pipeline_result`, and the panels read `case.pipeline_result`. |

### Characterization label set — actual vs spec

The prompt says labels must come from the actual implementation and lists valid examples: `light refined product`, `crude-like`, `heavy fuel-like`, `mixed/unknown`, `uncertain`.

**The code emits exactly two strings**, neither of which is in that list:
- `"crude_oil"`
- `"crude_oil (FLAG: implausibly large volume {N} m3 — likely a look-alike dark patch)"` when `vol_m3 > 50000`

Any UI showing the five-label set would be hardcoding a taxonomy the engine does not produce — explicitly forbidden by the prompt.

### Uncertainty layer — 1 of 8 factors exist

| Factor | Status |
|---|---|
| Detector/model confidence | **absent** — `detect_dark_spots` returns no per-detection score |
| Image quality | **absent** |
| Temporal persistence | **absent** — `max_products=1`, single scene |
| CFAR/U-Net/EO agreement | **absent** — no U-Net at all; EO receives only `lon,lat` (`pipeline.py:111`), never the SAR detections, so it is never spatially cross-checked |
| Weather/current consistency | **absent** |
| Look-alike risk | **absent server-side**; frontend fabricates it as `1 - confidence` |
| Transport uncertainty | **present** (weak) — `forecast.spread_deg`, `forecast.confidence` |
| Independent sensor agreement | **absent** |

Per the prompt, the seven absent factors must be **explicitly flagged as unavailable**, not omitted or synthesised.

### AIS fallback adapters

**None exist.** No LRIT, VMS, coastal radar, port records, or RF implementation — only two frontend strings advising the analyst to check them manually. No SAR *vessel* detection either (only dark-target detection). No vessel observation carries a `source_type`; `gfw_client.py:217` drops the temporal fields when building `positions`, and `pipeline.py:211-227` discards the vessel-level timestamps GFW *did* return.

---

## `pipeline_result` actual shape (what the frontend really receives)

13 top-level keys, always all present. **Stages return bare data — there is no per-stage wrapper.**

```jsonc
{
  "incident_id": "INC-2026-0006",
  "status": "ok",                  // ONLY "ok" | "no_particles"
  "sar_available": false,          // ctor succeeded, NOT "download worked"
  "gfw_available": true,           // ctor succeeded, NOT "API worked"  ← D-S6
  "warnings": [],                  // FLAT list; all stages append here
  "origin_centroid": [lon, lat],   // point only — no ellipse, no time window
  "origin_bbox": [minlon,minlat,maxlon,maxlat],
  "detections": [ {bbox_px, area_px, mean_db, centroid_px, bbox_geo?, centroid_geo?} ],
  "characterization": { slick_count, total_area_km2, est_volume_m3,
                        est_volume_barrels, est_volume_tonnes /*kg!*/,
                        likely_oil_type /*always "crude_oil"*/, per_slick[] },
  "age": { method, age_hours, age_min_hours, age_max_hours, stage_label,
           confidence, slick_contrast_db, wind_factor, mean_wind_ms,
           frames_used, warnings[] },       // the ONLY nested warnings list
  "eo":  { /* THREE different shapes: success / failure / ctor-failure */ },
  "forecast": { centroid, median_path[], bbox, spread_deg, confidence },
  "suspects": [ { mmsi, vessel_id, vessel_name, ship_type, geartype, cargo_type,
                  flag, imo, length, match_count /*= presence_hours*/,
                  presence_hours, last_seen, avg_lat, avg_lon, positions[],
                  anomaly_score, signals{}, evidence, transit_ok, transit_reason,
                  attribution_score, factors{proximity,duration,cargo,behaviour} } ]
}
```

**Absent throughout:** per-stage `status`, per-stage `quality`, per-stage `confidence`, `source_timestamp`, `run_id`. Milestone 2 requires all of these. Only `age.confidence` and `forecast.confidence` exist. Provider state lives on `Run.provider_status`, outside the blob.

**Field names that mislead:** `est_volume_tonnes` (kg), `match_count` (= presence_hours), `frames_used` (= dark-spot count), `forecast.confidence` (= particle retention), `eo.confirmed` (= one pixel).

---

## Deviations from the master prompt

1. **The prompt's premise is stale.** It is written as if Milestone 0 has not run, but `IMPLEMENTATION_STATUS.md` (30 KB) and `API_CONTRACT.md` already exist and `README.md:141-167` claims Milestones 0–9 complete. Much of Milestones 1, 6, 7 is genuinely done: async `/runs` endpoints, `RunResponse` with all 20 persisted fields, the full documented route set, approval-gated reports. I verified rather than rebuilt, per "do not expand scope."
2. **Milestone 0 deliverable written to a new file.** The prompt names `IMPLEMENTATION_STATUS.md`; overwriting a 30 KB existing document would destroy content, and this sandbox cannot delete files to undo that. Written to `MILESTONE_0_GAP_REPORT.md` instead.
3. **"Run the documented commands and record actual output" could not be honoured.** PyPI and npm are both 403 in this environment. Substituted source analysis and flagged every execution-dependent claim as **needs your run**.
4. **Reported baseline metrics reproduce, but only as aggregate arithmetic over the frozen per-incident CSV** — not a fresh model re-run. The README's differing re-run numbers remain unresolved and have a plausible cause (unseeded RNG).
5. **`git init` performed, plus two files added.** The project had no version control and this sandbox cannot delete files, so a rollback point was created before any edits: baseline commit `a9631d8` (101 files). Added `PRE_CLAUDE_CODE_BACKUP.tar.gz` (465 KB) and this report. Also `_deltest.txt`, an accidental probe file — **please delete it.** Three git lock files (`.git/HEAD.lock`, `.git/index.lock`, `.git/objects/maintenance.lock`) must be deleted before git will accept further commits.
6. **U-Net is absent, not merely unwired.** The prompt's uncertainty layer requires "CFAR/U-Net/EO agreement". With no checkpoint and no inference path, this factor cannot be computed and must be labelled unavailable rather than approximated.

---

## Prioritized plan

Ordered by "would this embarrass us in front of judges", not by effort.

### P0 — Honesty fixes. Small diffs, highest value. Do before any styling.
1. `quantifier.py:122` — divide by 1000, or rename to `est_mass_kg` and update consumers. *(D-S1, one line)*
2. `pipeline.py:170` and `:75` — set `available` only after a call that returns data, and append the caught exception to `warnings`. *(D-S6)*
3. `pipeline.py:224-225` — remove the bbox-centre position fallback; emit `null` and mark `proximity` as unscoreable. *(D-S2)*
4. `Panel1Detection.jsx:109` — fix the `data` `ReferenceError`. *(D-F1, one line, currently crashes the panel)*
5. Rename `overall_confidence` → `transport_age_confidence` and **stop deriving the oil/no-oil verdict from it**. Show "insufficient evidence for a detection verdict" until a real detector confidence exists. *(D-S7, D-F4)*
6. `pipeline.py:105` — pass the true scene count. *(D-S5)*
7. Add an `is_demo` flag to seeded cases and render a `DEMO DATA` badge from it. *(D8)*

### P1 — Security. Required by Milestone 6, currently failing.
8. Extract the admin-block into a shared dependency and apply it to `/runs`, `/runs/{id}`, `/notes` (read+write), `/audit`, `/generate-report`. *(D3)*
9. Add the ownership check to `PATCH /cases/{id}/status`. *(D2)*
10. Remove the `auth.py:13` secret fallback — fail loudly if `JWT_SECRET` is unset. Rotate the current one. *(D4)*
11. Authenticate or delete `/attribute/spill` and `/sar/search`. *(D5)*
12. Fix `_extract_confidence` in `case_routes.py`, or delete the dead `/run-pipeline` route. *(D1)*
13. Write the failing authorization test for each of the above first, so the passing suite is the acceptance criterion the prompt asks for.

### P2 — Make the real data legible. This is the frontend work you asked for.
14. **Design system** in `index.css`: tokens, type scale, spacing, dark operational palette. No structural change.
15. **`ErrorBoundary`** per panel so one bad field cannot blank the workspace. *(D-F7)*
16. **Fix `index.html`** — load `maplibre-gl.css`, drop the Mapbox stylesheet. *(D-F6)*
17. **Satellite basemap** with automatic fallback to OpenFreeMap vector tiles when `VITE_MAPBOX_TOKEN` is absent, so it degrades instead of breaking.
18. **Origin as a region, not a point** — surface the already-computed `std_dev` (`pipeline.py:300`) and draw an uncertainty ellipse. *(D-S12, cheap and visually significant)*
19. **Forecast cone** from `spread_deg` + `median_path`, with horizon, forcing, and particle count labelled — those three need adding to the `forecast` dict.
20. **Uncertainty panel that admits absence** — render all 8 factors, 7 marked *unavailable* with the reason. More credible than a full-looking gauge.
21. **Merge `Run` metadata into the panels** so each stage shows `provider_status`, warnings, and whether `null` means not-requested / failed / no-data. *(D-F8)*
22. **Score-driven vessel labels** with an explicit `insufficient evidence` threshold, replacing positional assignment. *(D-F3)*
23. **Candidate-reduction ratio** — needs the pre-filter count preserved at `pipeline.py:231`.

### P3 — Deferred, flagged rather than faked
24. Unseeded RNG → seed it, for evidentiary reproducibility. *(D-S10)*
25. `mean_db` sign convention — **investigate first**, may pin age at 3 h on all real scenes.
26. Particle deactivation on extraction failure. *(D-S8)*
27. Report export does not exist. Either build it or remove the UI affordance.
28. `rerun` / `override-rank` / `escalate` no-ops — implement or remove the buttons.
29. Delete `ais_filter.py::_get_mock_matches`. *(D-S11)*

**Recommendation:** P0 items 1–7 are roughly a dozen lines total and remove every "that number is wrong" question a judge could ask. P2 is the visual work you want, and it lands much better on top of P0.
