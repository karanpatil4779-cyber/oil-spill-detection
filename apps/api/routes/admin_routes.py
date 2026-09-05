"""Admin routes: user management, data source config, model registry, audit log."""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.db.models import (
    get_db, User, ModelVersion, DataSourceConfig, AuditLogEntry, SessionLocal, Run,
)
from apps.api.auth import hash_password
from apps.api.deps import require_role

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateUserRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str  # analyst | supervisor | admin


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    status: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    status: str
    created_at: str
    last_login: Optional[str]


class DataSourceRequest(BaseModel):
    source_type: str
    name: str
    endpoint: Optional[str] = None
    refresh_interval_minutes: int = 60
    is_active: bool = True


class DataSourceResponse(BaseModel):
    id: int
    source_type: str
    name: str
    endpoint: Optional[str]
    refresh_interval_minutes: int
    is_active: bool
    updated_at: str


class DeployModelRequest(BaseModel):
    model_type: str  # detection | transport | attribution
    version_tag: str
    notes: Optional[str] = None


class ModelVersionResponse(BaseModel):
    id: int
    model_type: str
    version_tag: str
    is_active: bool
    deployed_at: str
    notes: Optional[str]


class AuditEntryResponse(BaseModel):
    id: int
    actor_name: str
    action_type: str
    detail: Optional[dict]
    timestamp: str


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@router.get("/users", response_model=List[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        UserResponse(
            id=u.id, email=u.email, name=u.name, role=u.role, status=u.status,
            created_at=u.created_at.isoformat() if u.created_at else "",
            last_login=u.last_login.isoformat() if u.last_login else None,
        )
        for u in users
    ]


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(
    req: CreateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    if req.role == "admin" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create admin accounts")

    user = User(
        email=req.email,
        name=req.name,
        password_hash=hash_password(req.password),
        role=req.role,
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id, email=user.email, name=user.name, role=user.role, status=user.status,
        created_at=user.created_at.isoformat(),
        last_login=None,
    )


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    req: UpdateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.role is not None:
        user.role = req.role
    if req.status is not None:
        user.status = req.status
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id, email=user.email, name=user.name, role=user.role, status=user.status,
        created_at=user.created_at.isoformat() if user.created_at else "",
        last_login=user.last_login.isoformat() if user.last_login else None,
    )


# ---------------------------------------------------------------------------
# Data Source Configuration
# ---------------------------------------------------------------------------

@router.get("/data-sources", response_model=List[DataSourceResponse])
def list_data_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    sources = db.query(DataSourceConfig).all()
    return [
        DataSourceResponse(
            id=s.id, source_type=s.source_type, name=s.name, endpoint=s.endpoint,
            refresh_interval_minutes=s.refresh_interval_minutes, is_active=s.is_active,
            updated_at=s.updated_at.isoformat() if s.updated_at else "",
        )
        for s in sources
    ]


@router.put("/data-sources/{source_id}", response_model=DataSourceResponse)
def update_data_source(
    source_id: int,
    req: DataSourceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    source = db.query(DataSourceConfig).filter(DataSourceConfig.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    source.source_type = req.source_type
    source.name = req.name
    source.endpoint = req.endpoint
    source.refresh_interval_minutes = req.refresh_interval_minutes
    source.is_active = req.is_active
    source.updated_by = current_user.id
    db.commit()
    db.refresh(source)
    return DataSourceResponse(
        id=source.id, source_type=source.source_type, name=source.name, endpoint=source.endpoint,
        refresh_interval_minutes=source.refresh_interval_minutes, is_active=source.is_active,
        updated_at=source.updated_at.isoformat() if source.updated_at else "",
    )


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------

@router.get("/models", response_model=List[ModelVersionResponse])
def list_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    models = db.query(ModelVersion).order_by(ModelVersion.deployed_at.desc()).all()
    return [
        ModelVersionResponse(
            id=m.id, model_type=m.model_type, version_tag=m.version_tag,
            is_active=m.is_active, deployed_at=m.deployed_at.isoformat() if m.deployed_at else "",
            notes=m.notes,
        )
        for m in models
    ]


@router.post("/models/deploy", response_model=ModelVersionResponse, status_code=201)
def deploy_model(
    req: DeployModelRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    # Deactivate previous active version of same type
    prev = db.query(ModelVersion).filter(
        ModelVersion.model_type == req.model_type,
        ModelVersion.is_active == True,
    ).all()
    for p in prev:
        p.is_active = False

    mv = ModelVersion(
        model_type=req.model_type,
        version_tag=req.version_tag,
        is_active=True,
        deployed_by=current_user.id,
        notes=req.notes,
    )
    db.add(mv)
    db.commit()
    db.refresh(mv)
    return ModelVersionResponse(
        id=mv.id, model_type=mv.model_type, version_tag=mv.version_tag,
        is_active=mv.is_active, deployed_at=mv.deployed_at.isoformat(),
        notes=mv.notes,
    )


@router.post("/models/{model_id}/rollback", response_model=ModelVersionResponse)
def rollback_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    target = db.query(ModelVersion).filter(ModelVersion.id == model_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Model version not found")

    # Deactivate current active of same type
    prev = db.query(ModelVersion).filter(
        ModelVersion.model_type == target.model_type,
        ModelVersion.is_active == True,
    ).all()
    for p in prev:
        p.is_active = False

    target.is_active = True
    db.commit()
    db.refresh(target)
    return ModelVersionResponse(
        id=target.id, model_type=target.model_type, version_tag=target.version_tag,
        is_active=target.is_active, deployed_at=target.deployed_at.isoformat(),
        notes=target.notes,
    )


# ---------------------------------------------------------------------------
# System Audit Log
# ---------------------------------------------------------------------------

@router.get("/audit-log", response_model=List[AuditEntryResponse])
def get_audit_log(
    action_type: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    query = db.query(AuditLogEntry)
    if action_type:
        query = query.filter(AuditLogEntry.action_type == action_type)
    entries = query.order_by(AuditLogEntry.timestamp.desc()).limit(limit).all()
    return [
        AuditEntryResponse(
            id=e.id,
            actor_name=e.actor.name if e.actor else "System",
            action_type=e.action_type,
            detail=e.detail,
            timestamp=e.timestamp.isoformat() if e.timestamp else "",
        )
        for e in entries
    ]


# ---------------------------------------------------------------------------
# System Status (no investigation data)
# ---------------------------------------------------------------------------

class SystemStatusResponse(BaseModel):
    database: str
    providers: dict
    job_runner: dict


@router.get("/system-status", response_model=SystemStatusResponse)
def get_system_status(
    current_user: User = Depends(require_role("admin")),
):
    from apps.db.models import engine, Run
    from apps.jobs.runner import MAX_CONCURRENT_RUNS, RUN_LEVEL_MAX_RETRIES, STAGE_TIMEOUT_SECONDS

    db_status = "ok"
    try:
        with engine.connect():
            db_status = f"ok ({engine.dialect.name})"
    except Exception as e:
        db_status = f"error: {e}"

    providers = {
        "cdse": {"name": "Copernicus Data Space", "status": "check_required"},
        "gfw": {"name": "Global Fishing Watch", "status": "check_required"},
        "era5": {"name": "ERA5 / CDS", "status": "preprocessed"},
        "cmems": {"name": "CMEMS Currents", "status": "preprocessed"},
    }

    session = SessionLocal()
    try:
        running = session.query(Run).filter(Run.status == "running").count()
        queued = session.query(Run).filter(Run.status == "queued").count()
        failed_recent = session.query(Run).filter(Run.status == "failed").count()
    except Exception:
        running = queued = failed_recent = 0
    finally:
        session.close()

    return SystemStatusResponse(
        database=db_status,
        providers=providers,
        job_runner={
            "max_concurrent": MAX_CONCURRENT_RUNS,
            "max_retries": RUN_LEVEL_MAX_RETRIES,
            "timeout_seconds": STAGE_TIMEOUT_SECONDS,
            "running": running,
            "queued": queued,
            "failed_total": failed_recent,
        },
    )
