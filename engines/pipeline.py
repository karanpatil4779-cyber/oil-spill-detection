"""Full 6-stage marine oil-spill attribution pipeline.

Chains the individual engines into one end-to-end flow:

  1. Detection        : Sentinel-1 SAR dark-spot detection (engines/detection)
  2. Characterization : slick area/volume/type estimation   (engines/characterization)
  3. Metocean forcing : wind + currents forcing            (engines/metocean)
  4. Transport        : backward Lagrangian tracking        (engines/transport)
  5. AIS              : GFW real vessel tracks + registry   (engines/ais)
  6. Attribution      : ranked suspect vessels              (engines/attribution)

Each stage is optional and degrades gracefully if its data source is
unavailable (e.g. GFW key invalid, SAR product missing, pre-2017 incident).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from engines.transport.lagrangian_tracker import LagrangianTracker
from engines.attribution.ranker import AttributionRanker
from engines.characterization.quantifier import characterize_detections

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class PipelineOutput:
    incident_id: str
    status: str
    origin_centroid: Optional[List[float]] = None
    origin_bbox: Optional[List[float]] = None
    detections: List[Dict] = field(default_factory=list)
    characterization: Optional[Dict] = None
    age: Optional[Dict] = None
    eo: Optional[Dict] = None
    forecast: Optional[Dict] = None
    suspects: List[Dict] = field(default_factory=list)
    sar_available: bool = False
    gfw_available: bool = False
    warnings: List[str] = field(default_factory=list)


INCIDENT_FILES = {
    "msc_chitra_khalijia3_mumbai_2010": "data/processed/metocean/msc_chitra_khalijia3_mumbai_2010/final_metocean.nc",
    "mt_jipro_neftis_mumbai_2018": "data/processed/metocean/mt_jipro_neftis/final_metocean.nc",
    "gal_constructor_mumbai_2021": "data/processed/metocean/mumbai/final_metocean.nc",
    "ennore_chennai_coastal_2017": "data/processed/metocean/ennore_chennai_coastal_2017/final_metocean.nc",
    "kandla_gulf_kutch_2023": "data/processed/metocean/kandla_gulf_kutch_2023/final_metocean.nc",
}

DEFAULT_METOCEAN = "data/processed/metocean/mumbai/final_metocean.nc"


def resolve_metocean_file(incident_id: Optional[str]) -> str:
    if incident_id:
        path = INCIDENT_FILES.get(incident_id, DEFAULT_METOCEAN)
        if (PROJECT_ROOT / path).exists():
            return str(PROJECT_ROOT / path)
    if (PROJECT_ROOT / DEFAULT_METOCEAN).exists():
        return str(PROJECT_ROOT / DEFAULT_METOCEAN)
    return str(PROJECT_ROOT / "data/processed/metocean/mt_jipro_neftis/final_metocean.nc")


def _run_detection(lon, lat, date, band="VV", max_products=1):
    """Stage 1: optional SAR detection."""
    out = {"detections": [], "available": False, "warnings": []}
    try:
        from engines.detection.sar_detector import SARDetector
        det = SARDetector()
        out["available"] = True
        products = det.search_products(lon, lat, date, product_type="GRD", limit=max_products)
        if not products:
            out["warnings"].append("No Sentinel-1 product found for this date/location")
            return out
        product = products[0]
        logger.info(f"SAR: downloading {product['name']}")
        dl_dir = det.download_product(product["id"])
        detections = det.detect_from_product(str(dl_dir), band=band)
        out["detections"] = detections
    except Exception as e:
        out["warnings"].append(f"SAR detection skipped: {e}")
    return out


def _run_characterization(detections, **kw):
    if not detections:
        return None
    res = characterize_detections(detections, **kw)
    return res.__dict__


def _run_aging(detections, metocean_file, lon, lat, time, window_hours=48):
    """Estimate the age of a detected slick using SAR contrast + wind forcing."""
    from engines.aging.oil_age import estimate_oil_age, extract_mean_wind
    mean_wind = None
    try:
        mean_wind = extract_mean_wind(metocean_file, lon, lat, time, window_hours)
    except Exception as e:
        logger.warning(f"Wind extraction for age failed: {e}")
    res = estimate_oil_age(detections, mean_wind_ms=mean_wind, frames=max(1, len(detections) or 1))
    out = res.__dict__
    out["warnings"] = [w for w in out["warnings"] if w]
    return out


def _run_eo_detection(lon, lat, date):
    """Optional Sentinel-2 EO oil confirmation fused after SAR detection."""
    out = {"available": False, "confirmed": False, "reason": "EO not run", "detections": []}
    start = (date[:10])
    # search a ±5 day window to catch the nearest valid S2 overpass
    from datetime import datetime, timedelta
    try:
        d = datetime.fromisoformat(start)
        s = (d - timedelta(days=5)).strftime("%Y-%m-%d")
        e = (d + timedelta(days=5)).strftime("%Y-%m-%d")
    except Exception:
        s = start
        e = start
    try:
        from engines.detection.eo_detector import EODetector
        det = EODetector()
        out = det.detect_oil(lon, lat, s, e)
    except Exception as e:
        out["reason"] = f"EO detection skipped: {e}"
    return out


def _run_forward_forecast(tracker, lon, lat, time, duration_hours):
    """Predict future drift of the slick (forward Lagrangian forecast)."""
    try:
        forecast = tracker.forecast_ensemble(lon, lat, time,
                                             duration_hours=max(24, min(duration_hours, 72)),
                                             num_particles=200)
        return forecast
    except Exception as e:
        logger.warning(f"Forward forecast skipped: {e}")
        return None


def _run_transport(metocean_file, lon, lat, time, duration_hours):
    tracker = LagrangianTracker(metocean_file)
    particles = tracker.track_backward(lon, lat, time, duration_hours)
    if not particles:
        return None, None
    origin = tracker.compute_origin_probability(particles)
    return origin, tracker


def _run_ais(origin, detection_time, duration_hours):
    """Stage 5: GFW vessels in origin bbox + optional registry enrichment.

    The GFW 4Wings presence report already embeds identity fields (name, MMSI,
    flag, vessel type, geartype) alongside AIS presence positions, so the
    suspects are built directly from it. The /vessels/{id} identity endpoint
    requires a separate dataset permission some tokens lack (403); enrichment
    is therefore best-effort and never blocks attribution.
    """
    suspects = []
    available = False
    try:
        from engines.ais.gfw_client import GFWClient
        from datetime import datetime, timedelta

        gfw = GFWClient()
        available = True
        detection_dt = datetime.fromisoformat(detection_time)

        # GFW AIS coverage is reliable from ~2017 onward.
        if detection_dt.year < 2017:
            return suspects, available

        bbox = origin["bbox"]
        margin = 0.05
        search_bbox = [bbox[0]-margin, bbox[1]-margin, bbox[2]+margin, bbox[3]+margin]
        start = detection_dt - timedelta(hours=duration_hours)
        # 4Wings report requires UTC ISO-8601 with milliseconds (e.g. ...00.000Z).
        win = [
            f"{start:%Y-%m-%dT%H:%M:%S.000Z}",
            f"{detection_dt:%Y-%m-%dT%H:%M:%S.000Z}",
        ]
        raw = gfw.vessels_in_bbox_and_time(search_bbox, win)

        for entry in raw:
            vid = entry.get("vessel_id") or entry.get("vesselId") or entry.get("id", "")
            if not vid:
                continue
            mp = entry.get("mean_position") or {}
            track = entry.get("positions") or []
            last = entry.get("exit_timestamp") or detection_time

            # Best-effort registry enrichment (may 403 on tokens without the
            # vessel-identity dataset permission; identity already present in
            # the presence report, so a failure is harmless).
            length = None
            cargo_type = entry.get("ship_type", "Unknown")
            try:
                info = gfw.get_vessel(vid)
                vm = info.get("vessel", {}) if isinstance(info, dict) else {}
                length = vm.get("length") or None
                cargo_type = (
                    vm.get("cargoType", vm.get("shipType")) or cargo_type
                )
            except Exception:
                pass

            suspects.append({
                "mmsi": int(entry.get("mmsi") or 0),
                "vessel_id": vid,
                "vessel_name": entry.get("vessel_name", "Unknown"),
                "ship_type": entry.get("ship_type", "Unknown"),
                "geartype": entry.get("geartype", entry.get("ship_type", "Unknown")),
                "cargo_type": cargo_type,
                "flag": entry.get("flag", "Unknown"),
                "imo": entry.get("imo"),
                "length": length,
                "match_count": int(entry.get("presence_hours", 1) or 1),
                "presence_hours": float(entry.get("presence_hours", 0) or 0),
                "last_seen": str(last),
                "avg_lat": mp.get("lat") or (search_bbox[1]+search_bbox[3])/2,
                "avg_lon": mp.get("lon") or (search_bbox[0]+search_bbox[2])/2,
                "positions": entry.get("positions", []),
            })

        # Filter out irrelevant traffic and attach behavioural anomaly evidence.
        from engines.ais.behaviour import filter_and_enrich
        suspects = filter_and_enrich(suspects)
    except Exception as e:
        logger.warning(f"AIS stage skipped: {e}")
    return suspects, available


def _run_attribution(suspects, origin_centroid):
    ranker = AttributionRanker()
    cargo = {}
    for s in suspects:
        m = s.get("mmsi", 0)
        if m:
            cargo[m] = s.get("cargo_type", s.get("ship_type", "Unknown"))
    return ranker.rank_vessels(suspects, origin_centroid, cargo)


def run_pipeline(
    lon: float,
    lat: float,
    detection_time: str,
    duration_hours: int = 48,
    incident_id: Optional[str] = None,
    run_sar: bool = False,
    sar_date: Optional[str] = None,
    progress_callback=None,
) -> PipelineOutput:
    """Execute the full 6-stage pipeline.

    ``progress_callback`` is an optional callable ``(stage_name: str,
    progress_percent: float)`` invoked at stage boundaries. It is a pure
    instrumentation hook used by the async job runner to persist progress;
    it does not alter any scientific computation.
    """
    def _progress(stage: str, pct: float):
        if progress_callback:
            try:
                progress_callback(stage, pct)
            except Exception:  # instrumentation must never break the run
                pass

    out = PipelineOutput(
        incident_id=incident_id or "custom",
        status="ok",
        sar_available=False,
    )

    # Stage 1 & 2: Detection + Characterization (optional)
    if run_sar:
        sar_date = sar_date or detection_time[:10]
        _progress("detection", 5.0)
        det_res = _run_detection(lon, lat, sar_date)
        out.sar_available = det_res["available"]
        out.warnings += det_res["warnings"]
        out.detections = det_res["detections"]
        if out.detections:
            _progress("characterization", 12.0)
            out.characterization = _run_characterization(out.detections)
            logger.info(f"Characterization: volume={out.characterization['est_volume_m3']} m3")

    # Stage 3 & 4: Metocean + Transport (backward origin + forward forecast)
    _progress("metocean", 22.0)
    metocean_file = resolve_metocean_file(incident_id)
    _progress("transport", 30.0)
    origin, tracker = _run_transport(metocean_file, lon, lat, detection_time, duration_hours)
    if not origin:
        out.status = "no_particles"
        out.warnings.append("No transport particles remained in data domain")
        _progress("transport", 100.0)
        return out
    out.origin_centroid = origin["centroid"]
    out.origin_bbox = origin["bbox"]
    _progress("transport", 55.0)

    # Stage 4b: Forward drift forecast (predict future flow of the slick)
    if tracker is not None:
        _progress("forecast", 60.0)
        out.forecast = _run_forward_forecast(tracker, lon, lat, detection_time, duration_hours)

    # Stage 2b: Oil-spill age estimation (needs SAR detections + metocean wind)
    if out.detections and metocean_file:
        _progress("aging", 66.0)
        out.age = _run_aging(out.detections, metocean_file, lon, lat, detection_time)

    # Stage 1b: Sentinel-2 EO confirmation (optical, complements SAR)
    if run_sar:
        _progress("eo", 72.0)
        out.eo = _run_eo_detection(lon, lat, sar_date or detection_time)

    # Stage 5: AIS via GFW
    _progress("ais", 80.0)
    out.suspects, out.gfw_available = _run_ais(origin, detection_time, duration_hours)

    # Stage 6: Attribution
    if out.suspects:
        _progress("attribution", 92.0)
        out.suspects = _run_attribution(out.suspects, origin["centroid"])

    _progress("attribution", 100.0)
    return out
