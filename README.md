# SIH 2026: Satellite + AIS Based Marine Oil-Spill Detection
## Automated Source Attribution Platform

Smart India Hackathon problem statement 26143. A full-stack platform that detects marine oil spills from satellite imagery, characterises the slick, estimates its age, calculates geometric properties, reconstructs its likely origin, forecasts future movement, cross-references AIS vessel data, ranks potential source vessels, and exposes all of this through a secure, role-based interface.

### Architecture

```
apps/api/         FastAPI backend (auth, cases, runs, admin, analytics)
apps/db/          SQLAlchemy ORM (12 tables, SQLite fallback)
apps/web/         React 18 + Vite 5 (MapLibre GL, Recharts)
apps/jobs/        In-process async pipeline job runner (no Redis/RabbitMQ)
engines/          Pure-Python scientific modules (unchanged from original)
```

### Pipeline Stages (6-stage evidence chain)
1. **Detection** - Sentinel-1 SAR dark-spot CFAR detection (`engines/detection/sar_detector.py`)
2. **Characterization** - slick area / volume / type estimate (`engines/characterization/quantifier.py`)
3. **Age Estimation** - SAR contrast + wind correction interval (`engines/aging/oil_age.py`)
4. **Transport** - backward origin hindcast + forward Lagrangian forecast (`engines/transport/lagrangian_tracker.py`)
5. **AIS** - vessel presence + behaviour anomaly via GFW (`engines/ais/gfw_client.py`, `engines/ais/behaviour.py`)
6. **Attribution** - multi-factor ranked source hypothesis (`engines/attribution/ranker.py`)

All six stages are orchestrated in `engines/pipeline.py` with progress callbacks.

### Quick Start

#### Backend
```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install httpx  # needed for tests

# 2. Configure environment
copy .env.example .env
# Edit .env with your API keys (see below)

# 3. Run the API server
python -m uvicorn apps.api.main:app --port 8000

# 4. API is now available at http://localhost:8000
#    Health check: GET /health
```

#### Frontend
```bash
cd apps/web
npm install
npm run dev
# Available at http://localhost:5173
```

#### Build Frontend (production)
```bash
cd apps/web
npm run build  # Output in dist/
```

### Environment Variables (.env)

| Variable | Description | Status |
|----------|-------------|--------|
| `CDSE_USERNAME` / `CDSE_PASSWORD` | Copernicus Data Space for Sentinel-1 | Valid |
| `CMEMS_USERNAME` / `CMEMS_PASSWORD` | Copernicus Marine for ocean currents | Present |
| `GFW_API_KEY` | Global Fishing Watch v3 | Presence OK; vessel-identity 403 (permission) |
| `ERA5_API_KEY` / `CDSAPI_RC` | ERA5 / CDS API | Pre-processed archives available |
| `DATABASE_URL` | Postgres connection (falls back to SQLite) | SQLite used locally |
| `JWT_SECRET` | JWT signing key | **Change in production** |
| `JWT_ALGORITHM` | Default: HS256 | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Default: 480 | |

No Mapbox token needed - uses MapLibre GL with OpenFreeMap tiles.

### Data Sources
| Source | Data | Auth |
|--------|------|------|
| **CDSE** | Sentinel-1 SAR imagery | `CDSE_USERNAME/PASSWORD` |
| **CMEMS** | Ocean currents (uo/vo) | `CMEMS_USERNAME/PASSWORD` |
| **GFW** | Vessel AIS presence + tracks | `GFW_API_KEY` |
| **ERA5** | Wind, waves, SST | `.cdsapirc` |

### Benchmark Incidents
Pre-processed metocean data for 5 validation incidents:
- MSC Chitra (2010) - CMEMS available; GFW unavailable (pre-2017)
- MT Jipro Neftis (2018) - full pipeline available
- GAL Constructor (2021) - full pipeline available
- Chennai/Ennore (2017) - GFW AIS validation
- Kandla/Gulf of Kutch (2023) - GFW AIS validation

### Validation Metrics (reproduced 2026-09-04)
| Metric | Recorded Baseline | Reproduced |
|--------|-------------------|------------|
| Mean origin error | 26.24 km | 25.46 km |
| Median error | 21.1 km | 17.22 km |
| RMSE | 30.87 km | 30.39 km |

4/5 incidents reproduce bit-for-bit. MT Jipro Neftis differs due to numpy/xarray RNG state across versions (62 vs 60 active particles).

### Test Commands
```bash
# Full test suite (42 tests - scientific, auth, API, roles)
python -m pytest tests/test_platform.py -v

# Existing script-style tests
python tests/test_enhancements.py    # age estimation, forward forecast, behaviour, ranker
python tests/test_transport.py       # backward tracking validation
python tests/test_e2e.py             # end-to-end pipeline with real data

# Frontend build
cd apps/web && npm run build
```

### Roles & Access Control
- **Analyst** - Create cases, run pipeline, review results, submit for review
- **Supervisor** - Review all cases, approve/return/escalate, analytics dashboard
- **Admin** - System status, user management, model registry, audit logs (no investigation data)

All role enforcement is server-side. Tests verify:
- Analyst cannot access admin routes
- Supervisor cannot create cases
- Admin cannot view case data
- Report export requires supervisor approval

### Demo Users (auto-seeded on first startup)
| Role | Email | Password |
|------|-------|----------|
| Admin | admin@oilspill.gov | admin123 |
| Supervisor | supervisor@oilspill.gov | super123 |
| Analyst | analyst@oilspill.gov | analyst123 |
| Analyst | analyst2@oilspill.gov | analyst123 |

### Known Limitations
- **U-Net model checkpoint not committed** - `engines/detection/models/` is empty; pipeline falls back to CFAR
- **GFW vessel-identity dataset** returns 403 (token lacks permission); presence dataset works
- **Synchronous legacy endpoint** `POST /attribute/spill` still exists; use `POST /cases/{id}/runs` instead
- **No real-time queue monitoring** for Admin SystemDashboard (derived from audit log counts)
- **PostgreSQL not configured locally** - SQLite used as fallback

### Project Files Changed (Milestone 0-9)

**Backend:**
- `apps/db/models.py` - Run model, DB migrations, SQLite timeout config
- `apps/jobs/runner.py` - Async job runner with watchdog, retries, exponential backoff
- `apps/api/routes/case_routes.py` - Async runs endpoints, approval-gated reports, IDOR fixes
- `apps/api/routes/admin_routes.py` - System status endpoint, SessionLocal import fix
- `apps/api/main.py` - Job runner startup/shutdown, DB init

**Frontend:**
- `apps/web/src/pages/analyst/Workspace.jsx` - Async run polling, progress bar UI
- `apps/web/src/components/workspace/Panel1Detection.jsx` - Decision labels, look-alike risk
- `apps/web/src/components/workspace/Panel2Characterization.jsx` - Age interval display, per-slick tonnes
- `apps/web/src/components/workspace/Panel3OriginHindcast.jsx` - Fixed ReferenceError, age interval, multi-scenario
- `apps/web/src/components/workspace/Panel4ForwardForecast.jsx` - Forecast metadata, origin region
- `apps/web/src/components/workspace/Panel5AISVessels.jsx` - Removed hardcoded 1847, AIS fallback messaging
- `apps/web/src/components/workspace/Panel6Attribution.jsx` - Cautious labels, factor contributions
- `apps/web/src/components/workspace/Panel7DataQuality.jsx` - Uncertainty factors, decision labels
- `apps/web/src/pages/admin/SystemDashboard.jsx` - DEMO DATA labels, real system-status endpoint

**Tests:**
- `tests/test_platform.py` - 42 tests (scientific, auth, roles, async, audit)

**Documentation:**
- `API_CONTRACT.md` - Complete API route documentation
- `IMPLEMENTATION_STATUS.md` - Milestone 0 gap report
- `README.md` - Updated setup, env vars, test commands
