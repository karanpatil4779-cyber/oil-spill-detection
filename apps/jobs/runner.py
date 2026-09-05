"""In-process asynchronous pipeline job runner.

Chosen mechanism (see IMPLEMENTATION_STATUS.md, Deviations D4): a DB-backed
``runs`` table plus a small thread-pool executor with a watchdog. No external
queue broker (Redis/RabbitMQ) exists in the project dependencies, and the
local SQLite demo must stay runnable without extra services.

Run lifecycle:  queued -> running -> succeeded | failed | cancelled

Timeout & retry policy (explicit, documented):
  - Provider HTTP timeouts already live in the data clients:
      CDSE search 60s, download connect 30s / read 600s (sar_detector.py)
      GFW  _get 120s / _post 180s                                  (gfw_client.py)
  - Run-level retries: RUN_LEVEL_MAX_RETRIES (default 3) attempts with
    exponential backoff ``base=1.0s, factor=2.0`` on *transient* errors only
    (network I/O, 5xx/429). Permanent errors fail immediately.
  - Watchdog: any run left in ``running`` beyond STAGE_TIMEOUT_SECONDS
    (default 3600s) is force-failed with error_details, so a crashed/hung
    worker can never leave a case stuck in ``running``.
  - A failed download/provider error transitions the run to ``failed`` with
    error_details populated and the case to ``pipeline_status=error`` inside
    the same exception handler (never left in ``running``).
"""

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from apps.db.models import Run, Case, SessionLocal, ModelVersion

logger = logging.getLogger("jobs.runner")

# ---------------------------------------------------------------------------
# Policy knobs (env-overridable)
# ---------------------------------------------------------------------------
MAX_CONCURRENT_RUNS = int(os.getenv("PIPELINE_MAX_CONCURRENT_RUNS", "2"))
RUN_LEVEL_MAX_RETRIES = int(os.getenv("PIPELINE_MAX_RETRIES", "3"))
BACKOFF_BASE_SECONDS = float(os.getenv("PIPELINE_BACKOFF_BASE", "1.0"))
BACKOFF_FACTOR = float(os.getenv("PIPELINE_BACKOFF_FACTOR", "2.0"))
STAGE_TIMEOUT_SECONDS = int(os.getenv("PIPELINE_STAGE_TIMEOUT_SECONDS", "3600"))
WATCHDOG_INTERVAL_SECONDS = int(os.getenv("PIPELINE_WATCHDOG_INTERVAL", "10"))

# Tests set this False to enqueue without auto-dispatch.
_DISPATCH_ENABLED = not os.getenv("RUNNER_PAUSED", "").lower() in ("1", "true", "yes")

_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_RUNS, thread_name_prefix="pipeline-run")
_lock = threading.Lock()
_watchdog_thread = None
_shutdown = False


class RunCancelled(Exception):
    """Raised inside the worker when a cancel was requested mid-run."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.utcnow()


def _is_transient(err: BaseException) -> bool:
    """True for retryable (network / 5xx / 429) errors; False otherwise."""
    import requests
    if isinstance(err, (requests.exceptions.RequestException, TimeoutError, ConnectionError, OSError)):
        return True
    code = getattr(err, "status_code", None) or getattr(getattr(err, "response", None), "status_code", None)
    return code in {429, 500, 502, 503, 504}


def _backoff_seconds(attempt: int) -> float:
    return BACKOFF_BASE_SECONDS * (BACKOFF_FACTOR ** (attempt - 1))


def _snapshot_models():
    """Active model-version ids for reproducibility (best-effort)."""
    db = SessionLocal()
    try:
        rows = db.query(ModelVersion).filter(ModelVersion.is_active.is_(True)).all()
        return [
            {"id": m.id, "model_type": m.model_type, "version_tag": m.version_tag}
            for m in rows
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Model snapshot failed: {e}")
        return []
    finally:
        db.close()
# ---------------------------------------------------------------------------
# Persistence helpers (each opens a short-lived session: SQLite-friendly)
# ---------------------------------------------------------------------------

def _get_run(run_id: str) -> Run:
    db = SessionLocal()
    try:
        return db.query(Run).filter(Run.run_id == run_id).first()
    finally:
        db.close()


def _persist_progress(run_id: str, stage: str, pct: float):
    """Progress callback for run_pipeline; also checks cancel requests."""
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.run_id == run_id).first()
        if run is None:
            return
        if run.cancel_requested:
            raise RunCancelled("Cancel requested by user")
        run.current_stage = stage
        run.progress_percent = float(pct)
        db.commit()
    except RunCancelled:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Progress persist failed: {e}")
    finally:
        db.close()


def enqueue_run(case_id: int, requested_by: int, config: dict) -> str:
    """Create a queued Run row and (unless paused) dispatch the worker."""
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        run = Run(
            run_id=run_id,
            case_id=case_id,
            requested_by=requested_by,
            status="queued",
            current_stage="queued",
            progress_percent=0.0,
            configuration_snapshot=config,
            input_scene_ids=[],
            metocean_data_ids=[],
            model_version_ids=_snapshot_models(),
            provider_status={},
            warnings=[],
        )
        db.add(run)
        db.commit()
    finally:
        db.close()

    if _DISPATCH_ENABLED:
        _executor.submit(_run_worker_shield, run_id)
    return run_id


def _run_worker_shield(run_id: str):
    """Executor entry point — guarantees a terminal state, never stuck."""
    try:
        _execute_run(run_id)
    except BaseException as e:  # noqa: BLE001
        logger.exception(f"Unhandled worker error for {run_id}")
        _mark_failed(run_id, {"type": type(e).__name__, "message": str(e)})


def _mark_failed(run_id: str, error_details: dict):
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.run_id == run_id).first()
        if run is None or run.status in ("succeeded", "cancelled"):
            return
        run.status = "failed"
        run.error_details = error_details
        run.completed_at = _now()
        case = db.query(Case).filter(Case.id == run.case_id).first()
        if case:
            case.pipeline_status = "error"
            case.updated_at = _now()
        db.commit()
        logger.error(f"Run {run_id} failed: {error_details.get('message')}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to persist failure for {run_id}: {e}")
    finally:
        db.close()


def _mark_cancelled(run_id: str):
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.run_id == run_id).first()
        if run is None or run.status in ("succeeded", "failed"):
            return
        run.status = "cancelled"
        run.cancelled_at = _now()
        run.completed_at = _now()
        case = db.query(Case).filter(Case.id == run.case_id).first()
        if case:
            case.pipeline_status = "idle"
            case.updated_at = _now()
        db.commit()
        logger.info(f"Run {run_id} cancelled")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to persist cancellation for {run_id}: {e}")
    finally:
        db.close()
# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _invoke_pipeline(config: dict, progress_cb):
    """Run the full pipeline (importable separately so tests can monkeypatch).

    Applies the run-level retry policy: up to RUN_LEVEL_MAX_RETRIES attempts
    with exponential backoff on transient errors only.
    """
    from engines.pipeline import run_pipeline

    last_err = None
    for attempt in range(1, RUN_LEVEL_MAX_RETRIES + 1):
        try:
            out = run_pipeline(
                lon=config["lon"],
                lat=config["lat"],
                detection_time=f"{config['detection_date']}T12:00:00",
                duration_hours=config["duration_hours"],
                incident_id=config.get("incident_id"),
                run_sar=bool(config.get("run_sar", False)),
                sar_date=config.get("sar_date"),
                progress_callback=progress_cb,
            )
            return out
        except BaseException as e:  # noqa: BLE001
            last_err = e
            if attempt < RUN_LEVEL_MAX_RETRIES and _is_transient(e):
                wait = _backoff_seconds(attempt)
                logger.warning(f"Run attempt {attempt} transient failure ({e}); retrying in {wait:.1f}s")
                time.sleep(wait)
            else:
                break
    raise last_err  # type: ignore[misc]


def _execute_run(run_id: str):
    """Single run: queued(already) -> running -> succeeded | failed | cancelled."""
    run = _get_run(run_id)
    if run is None:
        logger.warning(f"Run {run_id} not found; nothing to do")
        return
    if run.cancel_requested or run.status == "cancelled":
        _mark_cancelled(run_id)
        return

    # Start
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.run_id == run_id).first()
        run.status = "running"
        run.started_at = _now()
        case = db.query(Case).filter(Case.id == run.case_id).first()
        if case:
            case.pipeline_status = "running"
            case.updated_at = _now()
        db.commit()
        config = dict(run.configuration_snapshot or {})
    finally:
        db.close()

    def _progress(stage, pct):
        _persist_progress(run_id, stage, pct)

    try:
        out = _invoke_pipeline(config, _progress)
    except RunCancelled:
        _mark_cancelled(run_id)
        return
    except BaseException as e:  # noqa: BLE001
        _mark_failed(run_id, {"type": type(e).__name__, "message": str(e)})
        return

    # Success: persist outputs + case result snapshot
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
    provider_status = {
        "sar": "ok" if out.sar_available and out.detections else ("warn" if out.sar_available else "unavailable"),
        "gfw": "ok" if out.gfw_available else "unavailable",
        "transport": "ok" if out.origin_centroid else "no_particles",
    }
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.run_id == run_id).first()
        run.status = "succeeded"
        run.completed_at = _now()
        run.current_stage = "complete"
        run.progress_percent = 100.0
        run.outputs = result
        run.warnings = out.warnings
        run.provider_status = provider_status
        case = db.query(Case).filter(Case.id == run.case_id).first()
        if case:
            case.pipeline_result = result
            case.pipeline_status = "done"
            case.overall_confidence = _extract_confidence(result)
            case.updated_at = _now()
            from apps.db.models import AuditLogEntry
            db.add(AuditLogEntry(
                case_id=case.id, actor_id=run.requested_by,
                action_type="pipeline_run",
                detail={"run_id": run_id, "status": "succeeded"},
            ))
        db.commit()
        logger.info(f"Run {run_id} succeeded")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"Persistence of succeeded run failed: {e}")
        _mark_failed(run_id, {"type": type(e).__name__, "message": str(e)})
    finally:
        db.close()

    # Best-effort: persist to legacy incidents table (unchanged behaviour)
    try:
        from apps.db.models import create_incident_record
        create_incident_record(
            out, config.get("lon"), config.get("lat"),
            config.get("detection_date"), config.get("duration_hours"),
        )
    except Exception:  # noqa: BLE001
        pass


def _extract_confidence(result: dict):
    age = result.get("age") or {}
    fc = result.get("forecast") or {}
    c1, c2 = age.get("confidence"), fc.get("confidence")
    if c1 is not None and c2 is not None:
        return round((c1 + c2) / 2, 3)
    return c1 or c2
# ---------------------------------------------------------------------------
# Cancellation + watchdog
# ---------------------------------------------------------------------------

def cancel_run(run_id: str) -> bool:
    """Cancel a run. Queued runs cancel immediately; running runs set a flag
    that the progress callback picks up at the next stage boundary."""
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.run_id == run_id).first()
        if run is None:
            return False
        if run.status == "queued":
            run.cancel_requested = True
            run.status = "cancelled"
            run.cancelled_at = _now()
            run.completed_at = _now()
            case = db.query(Case).filter(Case.id == run.case_id).first()
            if case:
                case.pipeline_status = "idle"
                case.updated_at = _now()
        elif run.status == "running":
            run.cancel_requested = True
        else:
            return False
        db.commit()
        return True
    finally:
        db.close()


def _hard_fail_stale_runs():
    """Force-fail runs that are still 'running' past the timeout window."""
    db = SessionLocal()
    try:
        deadline = datetime.utcnow() - timedelta(seconds=STAGE_TIMEOUT_SECONDS)
        stale = db.query(Run).filter(
            Run.status == "running",
            Run.started_at < deadline,
        ).all()
        for run in stale:
            run.status = "failed"
            run.error_details = {
                "type": "StageTimeout",
                "message": f"Run exceeded stage timeout of {STAGE_TIMEOUT_SECONDS}s",
            }
            run.completed_at = _now()
            case = db.query(Case).filter(Case.id == run.case_id).first()
            if case:
                case.pipeline_status = "error"
                case.updated_at = _now()
        if stale:
            db.commit()
            logger.warning(f"Watchdog force-failed {len(stale)} stale run(s)")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Watchdog error: {e}")
    finally:
        db.close()


def _watchdog_loop():
    while not _shutdown:
        try:
            _hard_fail_stale_runs()
        except Exception:  # noqa: BLE001
            logger.exception("Watchdog iteration failed")
        time.sleep(WATCHDOG_INTERVAL_SECONDS)


def start_runner():
    """Start the watchdog (executor is lazy). Reset stale 'running' runs left
    by a previous process."""
    global _watchdog_thread, _shutdown
    _shutdown = False
    if _watchdog_thread is None or not _watchdog_thread.is_alive():
        _watchdog_thread = threading.Thread(target=_watchdog_loop, name="run-watchdog", daemon=True)
        _watchdog_thread.start()
    # Recover any runs left dangling by a crash/restart.
    _hard_fail_stale_runs()
    logger.info("Pipeline job runner started (max_concurrent=%s, retries=%s, timeout=%ss)",
                MAX_CONCURRENT_RUNS, RUN_LEVEL_MAX_RETRIES, STAGE_TIMEOUT_SECONDS)


def stop_runner():
    global _shutdown
    _shutdown = True
    try:
        _executor.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        pass