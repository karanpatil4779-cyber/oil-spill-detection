"""Case CRUD routes for analysts and supervisors."""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.db.models import get_db, User, Case, CaseNote, AuditLogEntry, Incident, SessionLocal, Run
from apps.api.deps import get_current_user, require_role
import logging

logger = logging.getLogger("api.cases")

router = APIRouter(prefix="/cases", tags=["cases"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CaseCreateRequest(BaseModel):
    location_name: Optional[str] = None
    lon: float
    lat: float
    detection_date: str
    duration_hours: int = 48
    incident_id: Optional[str] = None


class CaseResponse(BaseModel):
    id: int
    case_number: str
    analyst_name: str
    status: str
    location_name: Optional[str]
    lon: Optional[float]
    lat: Optional[float]
    detection_date: Optional[str]
    overall_confidence: Optional[float]
    pipeline_result: Optional[dict]
    pipeline_status: str
    created_at: datetime
    updated_at: datetime


class CaseListResponse(BaseModel):
    cases: List[CaseResponse]
    total: int


class StatusUpdateRequest(BaseModel):
    status: str


class NoteCreateRequest(BaseModel):
    content: str


class NoteResponse(BaseModel):
    id: int
    author_name: str
    content: str
    is_supervisor_return: bool
    created_at: datetime


class RerunRequest(BaseModel):
    stage: str  # detection | characterization | origin | forecast | ais | attribution
    params: Optional[dict] = None


class RunCreateRequest(BaseModel):
    run_sar: bool = False
    sar_date: Optional[str] = None


class RunResponse(BaseModel):
    run_id: str
    case_id: int
    status: str
    current_stage: Optional[str]
    progress_percent: float
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    input_scene_ids: list = []
    metocean_data_ids: list = []
    configuration_snapshot: Optional[dict]
    model_version_ids: list = []
    provider_status: Optional[dict]
    outputs: Optional[dict]
    warnings: list = []
    error_details: Optional[dict]
    cancel_requested: bool = False


class OverrideRankRequest(BaseModel):
    vessel_id: str
    new_rank: int
    justification: str


def _to_run_response(run) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        case_id=run.case_id,
        status=run.status,
        current_stage=run.current_stage,
        progress_percent=float(run.progress_percent or 0.0),
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        input_scene_ids=run.input_scene_ids or [],
        metocean_data_ids=run.metocean_data_ids or [],
        configuration_snapshot=run.configuration_snapshot,
        model_version_ids=run.model_version_ids or [],
        provider_status=run.provider_status,
        outputs=run.outputs,
        warnings=run.warnings or [],
        error_details=run.error_details,
        cancel_requested=bool(run.cancel_requested),
    )


# ---------------------------------------------------------------------------
# Async pipeline-run routes (Milestone 1)
# ---------------------------------------------------------------------------

@router.post("/{case_id}/runs", response_model=RunResponse, status_code=202)
def create_case_run(
    case_id: int,
    req: RunCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("analyst")),
):
    """Create and queue an asynchronous pipeline run for a case.

    Returns 202 Accepted with a ``run_id``; progress is tracked via
    ``GET /runs/{run_id}``. The pipeline executes on the job runner thread,
    never on the HTTP request worker.
    """
    from apps.jobs.runner import enqueue_run

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")

    # Do not allow a second run to spin up while the case is actively running.
    active = db.query(Run).filter(
        Run.case_id == case_id,
        Run.status.in_(["queued", "running"]),
    ).first()
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"A run is already active for this case: {active.run_id}",
        )

    config = {
        "lon": case.lon,
        "lat": case.lat,
        "detection_date": case.detection_date,
        "duration_hours": case.duration_hours or 48,
        "incident_id": case.case_number,
        "run_sar": req.run_sar,
        "sar_date": req.sar_date,
    }
    run_id = enqueue_run(case_id, current_user.id, config)

    run = db.query(Run).filter(Run.run_id == run_id).first()
    _log_audit(db, case_id, current_user.id, "pipeline_run", {"run_id": run_id, "triggered": True})
    db.commit()
    return _to_run_response(run)


@router.get("/{case_id}/runs", response_model=List[RunResponse])
def list_case_runs(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if current_user.role not in ("supervisor", "admin") and case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")

    runs = db.query(Run).filter(Run.case_id == case_id).order_by(Run.created_at.desc()).all()
    return [_to_run_response(r) for r in runs]


@router.get("/{case_id}/runs/{run_id}", response_model=RunResponse)
def get_case_run(
    case_id: int,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if current_user.role not in ("supervisor", "admin") and case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")
    run = db.query(Run).filter(Run.run_id == run_id, Run.case_id == case_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_run_response(run)


@router.post("/{case_id}/runs/{run_id}/cancel", response_model=RunResponse)
def cancel_case_run(
    case_id: int,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("analyst")),
):
    from apps.jobs.runner import cancel_run
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")
    run = db.query(Run).filter(Run.run_id == run_id, Run.case_id == case_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not cancel_run(run_id):
        raise HTTPException(status_code=409, detail="Run cannot be cancelled in its current state")
    _log_audit(db, case_id, current_user.id, "pipeline_cancel", {"run_id": run_id})
    db.commit()
    run2 = db.query(Run).filter(Run.run_id == run_id).first()
    return _to_run_response(run2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_case_number(db: Session) -> str:
    last = db.query(Case).order_by(Case.id.desc()).first()
    if last:
        num = int(last.case_number.split("-")[-1]) + 1
    else:
        num = 1
    return f"INC-2026-{num:04d}"


def _case_to_response(case: Case) -> CaseResponse:
    return CaseResponse(
        id=case.id,
        case_number=case.case_number,
        analyst_name=case.analyst.name if case.analyst else "Unknown",
        status=case.status,
        location_name=case.location_name,
        lon=case.lon,
        lat=case.lat,
        detection_date=case.detection_date,
        overall_confidence=case.overall_confidence,
        pipeline_result=case.pipeline_result,
        pipeline_status=case.pipeline_status,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _log_audit(db: Session, case_id: int, actor_id: int, action_type: str, detail: dict = None):
    entry = AuditLogEntry(
        case_id=case_id,
        actor_id=actor_id,
        action_type=action_type,
        detail=detail,
    )
    db.add(entry)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=CaseListResponse)
def list_cases(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "admin":
        return CaseListResponse(cases=[], total=0)
    query = db.query(Case)
    if current_user.role == "analyst":
        query = query.filter(Case.analyst_id == current_user.id)
    if status_filter:
        query = query.filter(Case.status == status_filter)
    cases = query.order_by(Case.created_at.desc()).all()
    return CaseListResponse(
        cases=[_case_to_response(c) for c in cases],
        total=len(cases),
    )


@router.get("/{case_id}", response_model=CaseResponse)
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "admin":
        raise HTTPException(status_code=403, detail="Admin accounts cannot access investigation data")
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if current_user.role == "analyst" and case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")
    return _case_to_response(case)


@router.post("", response_model=CaseResponse, status_code=201)
def create_case(
    req: CaseCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("analyst")),
):
    case = Case(
        case_number=_next_case_number(db),
        analyst_id=current_user.id,
        status="in_progress",
        location_name=req.location_name,
        lon=req.lon,
        lat=req.lat,
        detection_date=req.detection_date,
        duration_hours=req.duration_hours,
    )
    db.add(case)
    db.flush()
    _log_audit(db, case.id, current_user.id, "case_created", {"location": req.location_name})
    db.commit()
    db.refresh(case)
    return _case_to_response(case)


@router.post("/{case_id}/run-pipeline")
def run_pipeline_on_case(
    case_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("analyst")),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")

    # If already running, don't start again
    if case.pipeline_status == "running":
        return {"message": "Pipeline already running", "case": _case_to_response(case), "result": case.pipeline_result}

    case.pipeline_status = "running"
    case.updated_at = datetime.utcnow()
    _log_audit(db, case.id, current_user.id, "pipeline_run", {"triggered": True})
    db.commit()

    background_tasks.add_task(_run_pipeline_bg, case_id, case.lon, case.lat,
                              case.detection_date, case.duration_hours, case.case_number)

    return {"message": "Pipeline started in background", "case": _case_to_response(case), "result": None}


def _run_pipeline_bg(case_id, lon, lat, detection_date, duration_hours, case_number):
    """Run the full pipeline in the background and persist the result."""
    try:
        from engines.pipeline import run_pipeline
        out = run_pipeline(
            lon=lon,
            lat=lat,
            detection_time=f"{detection_date}T12:00:00",
            duration_hours=duration_hours,
            incident_id=case_number,
        )

        result = {
            "incident_id": out.incident_id,
            "status": out.status,
            "origin_centroid": out.origin_centroid,
            "origin_bbox": out.origin_bbox,
            "detections": out.detections,
            "characterization": out.characterization,
            "age": out.age,
            "eo": out.eo,
            "forecast": out.forecast,
            "suspects": out.suspects,
            "sar_available": out.sar_available,
            "gfw_available": out.gfw_available,
            "warnings": out.warnings,
        }

        session = SessionLocal()
        try:
            case = session.query(Case).filter(Case.id == case_id).first()
            if case:
                case.pipeline_result = result
                case.overall_confidence = _extract_confidence(result)
                case.pipeline_status = "done"
                case.updated_at = datetime.utcnow()
                session.commit()
        finally:
            session.close()

        # Also persist to original incidents table (best-effort)
        try:
            from apps.db.models import create_incident_record
            create_incident_record(out, lon, lat, detection_date, duration_hours)
        except Exception:
            pass

    except Exception as e:
        session = SessionLocal()
        try:
            case = session.query(Case).filter(Case.id == case_id).first()
            if case:
                case.pipeline_status = "error"
                case.updated_at = datetime.utcnow()
                session.commit()
        finally:
            session.close()
        logger.error(f"Background pipeline for case {case_id} failed: {e}")


@router.post("/{case_id}/rerun")
def rerun_stage(
    case_id: int,
    req: RerunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("analyst")),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")

    _log_audit(db, case.id, current_user.id, f"rerun_{req.stage}", req.params or {})
    case.updated_at = datetime.utcnow()
    db.commit()

    return {"message": f"Re-run of {req.stage} queued", "case_id": case_id}


@router.patch("/{case_id}/status")
def update_status(
    case_id: int,
    req: StatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    valid_transitions = {
        "analyst": {
            "in_progress": ["pending_review", "insufficient_evidence", "closed"],
            "returned": ["pending_review", "insufficient_evidence", "closed"],
        },
        "supervisor": {
            "pending_review": ["approved", "returned"],
            "approved": ["closed"],
        },
    }
    allowed = valid_transitions.get(current_user.role, {}).get(case.status, [])
    if req.status not in allowed and current_user.role != "admin":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{case.status}' to '{req.status}' as {current_user.role}",
        )

    old_status = case.status
    case.status = req.status
    case.updated_at = datetime.utcnow()
    _log_audit(db, case.id, current_user.id, "status_change", {"from": old_status, "to": req.status})
    db.commit()
    return {"message": f"Status changed to {req.status}", "case_id": case_id}


@router.get("/{case_id}/notes", response_model=List[NoteResponse])
def get_notes(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if current_user.role == "analyst" and case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")
    notes = db.query(CaseNote).filter(CaseNote.case_id == case_id).order_by(CaseNote.created_at).all()
    return [
        NoteResponse(
            id=n.id,
            author_name=n.author.name if n.author else "Unknown",
            content=n.content,
            is_supervisor_return=n.is_supervisor_return,
            created_at=n.created_at,
        )
        for n in notes
    ]


@router.post("/{case_id}/notes", response_model=NoteResponse, status_code=201)
def add_note(
    case_id: int,
    req: NoteCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if current_user.role == "analyst" and case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")

    note = CaseNote(
        case_id=case_id,
        author_id=current_user.id,
        content=req.content,
        is_supervisor_return=False,
    )
    db.add(note)
    _log_audit(db, case_id, current_user.id, "note_added", {"length": len(req.content)})
    db.commit()
    db.refresh(note)
    return NoteResponse(
        id=note.id,
        author_name=current_user.name,
        content=note.content,
        is_supervisor_return=note.is_supervisor_return,
        created_at=note.created_at,
    )


@router.post("/{case_id}/return")
def return_for_revision(
    case_id: int,
    req: NoteCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("supervisor")),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.status != "pending_review":
        raise HTTPException(status_code=400, detail="Case not pending review")
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Return note is required")

    case.status = "returned"
    case.updated_at = datetime.utcnow()

    note = CaseNote(
        case_id=case_id,
        author_id=current_user.id,
        content=req.content,
        is_supervisor_return=True,
    )
    db.add(note)
    _log_audit(db, case_id, current_user.id, "returned_for_revision", {"note_length": len(req.content)})
    db.commit()
    return {"message": "Case returned for revision", "case_id": case_id}


@router.post("/{case_id}/approve")
def approve_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("supervisor")),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.status != "pending_review":
        raise HTTPException(status_code=400, detail="Case not pending review")

    case.status = "approved"
    case.updated_at = datetime.utcnow()
    _log_audit(db, case_id, current_user.id, "approved", None)
    db.commit()
    return {"message": "Case approved", "case_id": case_id}


@router.post("/{case_id}/escalate")
def escalate_case(
    case_id: int,
    req: NoteCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("supervisor")),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    _log_audit(db, case_id, current_user.id, "escalated", {"reason": req.content})
    db.commit()
    return {"message": "Case escalated", "case_id": case_id}


@router.post("/{case_id}/override-rank")
def override_rank(
    case_id: int,
    req: OverrideRankRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("analyst")),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")

    _log_audit(db, case_id, current_user.id, "rank_override", {
        "vessel_id": req.vessel_id,
        "new_rank": req.new_rank,
        "justification": req.justification,
    })
    case.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Rank override logged", "case_id": case_id}


@router.post("/{case_id}/generate-report")
def generate_report(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from apps.db.models import Report
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if current_user.role == "analyst" and case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")

    if case.status != "approved":
        raise HTTPException(
            status_code=400,
            detail="Report generation requires supervisor approval. Current status: " + case.status,
        )

    report = Report(
        case_id=case_id,
        generated_by=current_user.id,
        pdf_path=f"reports/{case.case_number}.pdf",
    )
    db.add(report)
    _log_audit(db, case_id, current_user.id, "report_generated", None)
    db.commit()
    return {"message": "Report generated", "case_number": case.case_number, "pdf_path": report.pdf_path}


@router.get("/{case_id}/audit")
def get_case_audit(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if current_user.role == "analyst" and case.analyst_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your case")

    entries = db.query(AuditLogEntry).filter(AuditLogEntry.case_id == case_id).order_by(AuditLogEntry.timestamp).all()
    return [
        {
            "id": e.id,
            "actor": e.actor.name if e.actor else "Unknown",
            "action_type": e.action_type,
            "detail": e.detail,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in entries
    ]


def _extract_confidence(result: dict) -> Optional[float]:
    """Detection confidence for Case.overall_confidence.

    Previously this did ``result.get("age", {}).get("confidence")``. When a run
    has no detections the pipeline stores ``age`` as ``None``, and a present key
    with a ``None`` value means the ``{}`` default never applies — so this raised
    AttributeError before the surrounding commit, discarding the whole
    pipeline_result and leaving every case in state "error".
    """
    from engines.assessment import stored_confidence
    return stored_confidence(result or {})
