"""Supervisor analytics routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from apps.db.models import get_db, User, Case
from apps.api.deps import require_role

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/throughput")
def case_throughput(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("supervisor", "admin")),
):
    total = db.query(Case).count()
    by_status = dict(
        db.query(Case.status, func.count(Case.id))
        .group_by(Case.status)
        .all()
    )
    return {
        "total_cases": total,
        "by_status": by_status,
    }


@router.get("/candidate-ratios")
def candidate_ratios(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("supervisor", "admin")),
):
    cases = db.query(Case).filter(Case.pipeline_result.isnot(None)).all()
    ratios = []
    for c in cases:
        result = c.pipeline_result or {}
        suspects = result.get("suspects", [])
        ratios.append({
            "case_number": c.case_number,
            "candidates_found": len(suspects),
        })
    return {"cases": ratios, "count": len(ratios)}


@router.get("/evidence-rate")
def evidence_rate(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("supervisor", "admin")),
):
    total = db.query(Case).count()
    insufficient = db.query(Case).filter(Case.status == "insufficient_evidence").count()
    closed = db.query(Case).filter(Case.status == "closed").count()
    approved = db.query(Case).filter(Case.status == "approved").count()
    return {
        "total": total,
        "insufficient_evidence": insufficient,
        "closed": closed,
        "approved": approved,
        "insufficient_rate": round(insufficient / total, 3) if total > 0 else 0,
    }


@router.get("/analyst-performance")
def analyst_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("supervisor", "admin")),
):
    analysts = db.query(User).filter(User.role == "analyst").all()
    result = []
    for a in analysts:
        case_count = db.query(Case).filter(Case.analyst_id == a.id).count()
        approved = db.query(Case).filter(Case.analyst_id == a.id, Case.status == "approved").count()
        result.append({
            "analyst_name": a.name,
            "total_cases": case_count,
            "approved": approved,
            "approval_rate": round(approved / case_count, 3) if case_count > 0 else 0,
        })
    return {"analysts": result}
