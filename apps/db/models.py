"""SQLAlchemy ORM models for persistent storage of incidents, detections,
transport results, suspects, attribution, users, cases, audit logs,
model versions, data-source configs and reports.

Wired to Postgres via DATABASE_URL from .env (falls back to SQLite for
local dev / demo)."""

import os
import logging
from datetime import datetime

import shutil

from sqlalchemy import (
    create_engine, Column, Float, Integer, String, DateTime, Text,
    ForeignKey, JSON, Boolean, inspect, text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

Base = declarative_base()

_DEFAULT_URL = "sqlite:///oil_spill.db"


def _test_connect(url: str) -> bool:
    try:
        eng = create_engine(url)
        with eng.connect():
            return True
    except Exception as e:
        logger.warning(f"DB URL not reachable ({url}): {e}")
        return False
    finally:
        eng.dispose()


def _engine_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        if _test_connect(url):
            return url
        logger.warning("DATABASE_URL not reachable; falling back to SQLite")
        return _DEFAULT_URL
    return _DEFAULT_URL


def _make_engine():
    url = _engine_url()
    kwargs = {"echo": False}
    if url.startswith("sqlite"):
        # Allow the job-runner worker threads + watchdog to open short-lived
        # sessions on the same SQLite file without spurious "database is
        # locked" errors.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return create_engine(url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ---------------------------------------------------------------------------
# Original models (kept for pipeline persistence)
# ---------------------------------------------------------------------------

class Incident(Base):
    """A recorded / analysed marine oil-spill incident."""
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)
    incident_id = Column(String, unique=True, index=True)
    name = Column(String)
    date = Column(String)
    lon = Column(Float)
    lat = Column(Float)
    duration_hours = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    detections = relationship("Detection", back_populates="incident", cascade="all, delete-orphan")
    suspects = relationship("AttributionResult", back_populates="incident", cascade="all, delete-orphan")


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"))
    product_name = Column(String)
    band = Column(String)
    bbox_px = Column(JSON)
    bbox_geo = Column(JSON)
    area_km2 = Column(Float)
    est_volume_m3 = Column(Float)
    est_volume_barrels = Column(Float)
    est_volume_tonnes = Column(Float)

    incident = relationship("Incident", back_populates="detections")


class TransportResult(Base):
    __tablename__ = "transport_results"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"))
    centroid_lon = Column(Float)
    centroid_lat = Column(Float)
    bbox = Column(JSON)
    particles = Column(Integer)

    incident = relationship("Incident")


class AttributionResult(Base):
    __tablename__ = "attribution_results"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"))
    mmsi = Column(Integer)
    vessel_name = Column(String)
    ship_type = Column(String)
    cargo_type = Column(String)
    flag = Column(String)
    attribution_score = Column(Float)
    factors = Column(JSON)

    incident = relationship("Incident", back_populates="suspects")


# ---------------------------------------------------------------------------
# New models for role-based platform
# ---------------------------------------------------------------------------

class User(Base):
    """Platform user with role-based access."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="analyst")  # analyst | supervisor | admin
    status = Column(String, nullable=False, default="active")  # active | deactivated
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    cases = relationship("Case", back_populates="analyst", foreign_keys="Case.analyst_id")
    audit_entries = relationship("AuditLogEntry", back_populates="actor", foreign_keys="AuditLogEntry.actor_id")


class Case(Base):
    """An investigation case created by an analyst."""
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True)
    case_number = Column(String, unique=True, index=True)  # e.g. INC-2026-001
    analyst_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False, default="in_progress")
    # in_progress | pending_review | returned | approved | closed | insufficient_evidence

    # Investigation input
    location_name = Column(String, nullable=True)
    lon = Column(Float, nullable=True)
    lat = Column(Float, nullable=True)
    detection_date = Column(String, nullable=True)
    duration_hours = Column(Integer, default=48)

    # Pipeline result snapshot (JSON blob of full pipeline output)
    pipeline_result = Column(JSON, nullable=True)

    # Pipeline execution status: idle | running | done | error
    pipeline_status = Column(String, nullable=False, default="idle", server_default="idle")

    # Overall confidence
    overall_confidence = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analyst = relationship("User", back_populates="cases", foreign_keys=[analyst_id])
    notes = relationship("CaseNote", back_populates="case", cascade="all, delete-orphan")
    audit_entries = relationship("AuditLogEntry", back_populates="case", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="case", cascade="all, delete-orphan")
    runs = relationship("Run", back_populates="case", cascade="all, delete-orphan")


class CaseNote(Base):
    """Notes attached to a case by analysts or supervisors."""
    __tablename__ = "case_notes"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    is_supervisor_return = Column(Boolean, default=False)  # True if this is a return-for-revision note
    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("Case", back_populates="notes")
    author = relationship("User")


class AuditLogEntry(Base):
    """Immutable log of every action on a case or system event."""
    __tablename__ = "audit_log_entries"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)  # null for system-level events
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action_type = Column(String, nullable=False)  # e.g. pipeline_rerun, param_change, override_rank, status_change
    detail = Column(JSON, nullable=True)  # structured detail of what changed
    timestamp = Column(DateTime, default=datetime.utcnow)

    case = relationship("Case", back_populates="audit_entries")
    actor = relationship("User", back_populates="audit_entries")


class ModelVersion(Base):
    """Tracks deployed model versions for reproducibility."""
    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True)
    model_type = Column(String, nullable=False)  # detection | transport | attribution
    version_tag = Column(String, nullable=False)
    is_active = Column(Boolean, default=False)
    deployed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    deployed_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)


class DataSourceConfig(Base):
    """Configuration for external data feeds."""
    __tablename__ = "data_source_configs"

    id = Column(Integer, primary_key=True)
    source_type = Column(String, nullable=False)  # satellite | ais | metocean
    name = Column(String, nullable=False)
    endpoint = Column(String, nullable=True)
    refresh_interval_minutes = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Report(Base):
    """Generated PDF reports for finalized cases."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    generated_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    pdf_path = Column(String, nullable=True)
    generated_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("Case", back_populates="reports")
    generator = relationship("User")


class Run(Base):
    """A single asynchronous pipeline execution for a case.

    Lifecycle: queued -> running -> succeeded | failed | cancelled.
    Persists every field required for reproducibility + auditability.
    """
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True)
    run_id = Column(String, unique=True, index=True, nullable=False)  # e.g. run_<uuid4-hex>
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, nullable=False, default="queued")  # queued|running|succeeded|failed|cancelled
    current_stage = Column(String, nullable=True)
    progress_percent = Column(Float, default=0.0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancel_requested = Column(Boolean, default=False)

    # Inputs & reproducibility snapshot
    input_scene_ids = Column(JSON, nullable=True)
    metocean_data_ids = Column(JSON, nullable=True)
    configuration_snapshot = Column(JSON, nullable=True)
    model_version_ids = Column(JSON, nullable=True)
    provider_status = Column(JSON, nullable=True)

    # Outputs
    outputs = Column(JSON, nullable=True)
    warnings = Column(JSON, nullable=True)
    error_details = Column(JSON, nullable=True)

    case = relationship("Case", back_populates="runs")
    requester = relationship("User")
# ---------------------------------------------------------------------------
# DB init and helpers
# ---------------------------------------------------------------------------

def _backup_sqlite(url: str) -> None:
    """Keep a one-time copy of a pre-existing SQLite DB before we migrate it."""
    try:
        if url.startswith("sqlite:///"):
            db_file = url.replace("sqlite:///", "", 1)
            if os.path.exists(db_file):
                backup = f"{db_file}.bak"
                if not os.path.exists(backup):
                    shutil.copy2(db_file, backup)
                    logger.info(f"Backed up existing DB -> {backup}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"DB backup skipped: {e}")


def run_migrations() -> None:
    """Add columns that newer ORM models require but that a pre-existing
    database (SQLite dev DB, older Postgres schema) may be missing.

    `create_all` never alters an existing table, so we ALTER TABLE for every
    modelled column absent from the live schema. New tables are created by
    create_all; this only fills missing columns. Idempotent + non-fatal.
    """
    if engine.dialect.name == "sqlite":
        _backup_sqlite(str(engine.url))
    try:
        insp = inspect(engine)
        with engine.begin() as conn:
            for table_name, table in Base.metadata.tables.items():
                if not insp.has_table(table_name):
                    continue
                existing = {c["name"] for c in insp.get_columns(table_name)}
                for col_name, col in table.columns.items():
                    if col_name in existing:
                        continue
                    type_sql = col.type.compile(dialect=engine.dialect)
                    default_clause = ""
                    if col.server_default is not None:
                        raw = col.server_default.arg
                        default_clause = f" DEFAULT {raw!r}"
                    if engine.dialect.name == "postgresql":
                        stmt = (
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN IF NOT EXISTS {col_name} {type_sql}{default_clause}"
                        )
                    else:
                        stmt = (
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {col_name} {type_sql}{default_clause}"
                        )
                    conn.execute(text(stmt))
                    logger.info(f"Migration: added column {table_name}.{col_name}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"DB migration failed (non-fatal): {e}")


def init_db() -> None:
    logger.info(f"Initialising DB at {engine.url}")
    Base.metadata.create_all(bind=engine)
    run_migrations()


def create_incident_record(pipeline_out, lon, lat, detection_time, duration_hours):
    """Persist a full pipeline result. Returns the Incident ORM object."""
    session = SessionLocal()
    try:
        inc = Incident(
            incident_id=pipeline_out.incident_id,
            name=pipeline_out.incident_id,
            date=detection_time,
            lon=lon,
            lat=lat,
            duration_hours=duration_hours,
        )
        session.add(inc)
        session.flush()

        if pipeline_out.characterization:
            for det in pipeline_out.characterization.get("per_slick", []):
                session.add(Detection(
                    incident_id=inc.id,
                    product_name="Sentinel-1",
                    band="VV",
                    bbox_px=det.get("bbox_px"),
                    bbox_geo=det.get("bbox_geo"),
                    area_km2=det.get("area_km2"),
                    est_volume_m3=det.get("est_volume_m3"),
                    est_volume_barrels=det.get("est_volume_barrels"),
                    est_volume_tonnes=det.get("est_volume_tonnes"),
                ))

        if pipeline_out.origin_centroid:
            session.add(TransportResult(
                incident_id=inc.id,
                centroid_lon=pipeline_out.origin_centroid[0],
                centroid_lat=pipeline_out.origin_centroid[1],
                bbox=pipeline_out.origin_bbox,
                particles=100,
            ))

        for s in pipeline_out.suspects:
            session.add(AttributionResult(
                incident_id=inc.id,
                mmsi=s.get("mmsi", 0),
                vessel_name=s.get("vessel_name", "Unknown"),
                ship_type=s.get("ship_type", "Unknown"),
                cargo_type=s.get("cargo_type", "Unknown"),
                flag=s.get("flag", "Unknown"),
                attribution_score=s.get("attribution_score", 0.0),
                factors=s.get("factors"),
            ))

        session.commit()
        return inc
    except Exception as e:
        session.rollback()
        logger.error(f"DB persistence failed: {e}")
        return None
    finally:
        session.close()


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    print(f"DB schema initialised at {engine.url}")
