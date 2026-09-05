"""Marine Oil-Spill Attribution API — main application entry point.

Wires all route modules, handles CORS, and initialises the DB on startup."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import logging
import os

logger = logging.getLogger("api")

app = FastAPI(title="Marine Oil-Spill Attribution API")

# Allow configurable CORS origins (comma-separated) for production deploy.
# Falls back to the local dev origins when CORS_ORIGINS is not set.
_cors = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
allow_origins = [o.strip() for o in _cors.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Import and register routers
# ---------------------------------------------------------------------------
from apps.api.routes.auth_routes import router as auth_router
from apps.api.routes.case_routes import router as case_router
from apps.api.routes.admin_routes import router as admin_router
from apps.api.routes.analytics_routes import router as analytics_router

app.include_router(auth_router)
app.include_router(case_router)
app.include_router(admin_router)
app.include_router(analytics_router)


# ---------------------------------------------------------------------------
# Health / legacy routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "message": "Marine Oil-Spill Attribution API is running.",
        "stages": [
            "detection", "characterization", "metocean",
            "transport", "ais", "attribution",
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Legacy pipeline endpoint (kept for backward compatibility)
# ---------------------------------------------------------------------------

class SpillRequest(BaseModel):
    lon: float
    lat: float
    detection_time: str
    duration_hours: int = 48
    incident_id: Optional[str] = None
    run_sar: bool = False
    sar_date: Optional[str] = None


class AttributionResult(BaseModel):
    incident_id: str
    status: str
    origin_centroid: Optional[List[float]] = None
    origin_bbox: Optional[List[float]] = None
    detections: List[Dict] = []
    characterization: Optional[Dict] = None
    age: Optional[Dict] = None
    eo: Optional[Dict] = None
    forecast: Optional[Dict] = None
    suspects: List[Dict] = []
    sar_available: bool = False
    gfw_available: bool = False
    warnings: List[str] = []
    persisted: bool = False


@app.post("/attribute/spill", response_model=AttributionResult)
async def attribute_spill(request: SpillRequest):
    from engines.pipeline import run_pipeline
    try:
        out = run_pipeline(
            lon=request.lon,
            lat=request.lat,
            detection_time=request.detection_time,
            duration_hours=request.duration_hours,
            incident_id=request.incident_id,
            run_sar=request.run_sar,
            sar_date=request.sar_date,
        )

        persisted = False
        try:
            from apps.db.models import create_incident_record
            create_incident_record(
                out, request.lon, request.lat,
                request.detection_time, request.duration_hours,
            )
            persisted = True
        except Exception as e:
            logger.warning(f"DB persistence skipped: {e}")

        return AttributionResult(
            incident_id=out.incident_id,
            status=out.status,
            origin_centroid=out.origin_centroid,
            origin_bbox=out.origin_bbox,
            detections=out.detections,
            characterization=out.characterization,
            age=out.age,
            eo=out.eo,
            forecast=out.forecast,
            suspects=out.suspects,
            sar_available=out.sar_available,
            gfw_available=out.gfw_available,
            warnings=out.warnings,
            persisted=persisted,
        )

    except Exception as e:
        logger.error(f"Attribution pipeline failed: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sar/search")
async def search_sar(lon: float, lat: float, date: str, product_type: str = "GRD", limit: int = 5):
    try:
        from engines.detection.sar_detector import SARDetector
        det = SARDetector()
        products = det.search_products(lon, lat, date, product_type=product_type, limit=limit)
        return {"products": products, "count": len(products)}
    except Exception as e:
        return {"error": str(e), "products": [], "count": 0}


# ---------------------------------------------------------------------------
# Seed default admin + demo users on startup (dev only)
# ---------------------------------------------------------------------------

@app.on_event("startup")
def seed_defaults():
    from apps.db.models import SessionLocal, User, DataSourceConfig, init_db
    from apps.api.auth import hash_password
    from apps.jobs.runner import start_runner

    # Start the async pipeline job runner (watchdog + stale-run recovery).
    try:
        start_runner()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Job runner start failed (non-fatal): {e}")

    init_db()
    db = SessionLocal()
    try:
        # Create default admin if no users exist
        if db.query(User).count() == 0:
            admin = User(
                email="admin@oilspill.gov",
                name="System Admin",
                password_hash=hash_password("admin123"),
                role="admin",
                status="active",
            )
            supervisor = User(
                email="supervisor@oilspill.gov",
                name="Dr. Priya Sharma",
                password_hash=hash_password("super123"),
                role="supervisor",
                status="active",
            )
            analyst = User(
                email="analyst@oilspill.gov",
                name="Ravi Kumar",
                password_hash=hash_password("analyst123"),
                role="analyst",
                status="active",
            )
            analyst2 = User(
                email="analyst2@oilspill.gov",
                name="Anita Desai",
                password_hash=hash_password("analyst123"),
                role="analyst",
                status="active",
            )
            db.add_all([admin, supervisor, analyst, analyst2])
            db.commit()
            logger.info("Seeded default users: admin, supervisor, analyst, analyst2")

        # Seed default data source configs
        if db.query(DataSourceConfig).count() == 0:
            sources = [
                DataSourceConfig(source_type="satellite", name="Bhoonidhi (Sentinel-1)", endpoint="https://bhoonidhi.nrsc.gov.in", refresh_interval_minutes=360),
                DataSourceConfig(source_type="satellite", name="Copernicus Open Access Hub", endpoint="https://catalogue.dataspace.copernicus.eu", refresh_interval_minutes=360),
                DataSourceConfig(source_type="ais", name="Global Fishing Watch v3", endpoint="https://globalfishingwatch.org/api/v3", refresh_interval_minutes=60),
                DataSourceConfig(source_type="metocean", name="ERA5 (ECMWF)", endpoint="https://cds.climate.copernicus.eu", refresh_interval_minutes=720),
                DataSourceConfig(source_type="metocean", name="CMEMS Global Currents", endpoint="https://marine.copernicus.eu", refresh_interval_minutes=720),
            ]
            db.add_all(sources)
            db.commit()
            logger.info("Seeded default data source configs")

    except Exception as e:
        logger.warning(f"Seeding failed (non-fatal): {e}")
    finally:
        db.close()


@app.on_event("shutdown")
def stop_runner():
    from apps.jobs.runner import stop_runner as _stop
    try:
        _stop()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Job runner stop failed: {e}")
