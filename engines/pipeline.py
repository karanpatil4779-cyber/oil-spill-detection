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
    # Positional spread of the back-tracked particle cloud, in degrees
    # [lon, lat]. Computed by the tracker; surfaced so the UI can draw an
    # uncertainty region instead of implying the centroid is a fix.
    origin_std_dev: Optional[List[float]] = None
    # Analyst-facing probabilistic origin zone (see engines/transport/origin_zone)
    origin_zone: Optional[Dict] = None
    detections: List[Dict] = field(default_factory=list)
    characterization: Optional[Dict] = None
    age: Optional[Dict] = None
    eo: Optional[Dict] = None
    forecast: Optional[Dict] = None
    suspects: List[Dict] = field(default_factory=list)
    # Look-alike screening summary (Feature 2), attached after the SAR stage.
    lookalike_filter: Optional[Dict] = None
    # ``*_available`` means "the provider was called and returned usable data".
    # It is deliberately NOT set from a successful constructor. ``*_requested``
    # distinguishes "we never asked" from "we asked and it failed" — without it
    # a skipped stage and a broken provider look identical downstream.
    sar_available: bool = False
    sar_requested: bool = False
    sar_scenes_used: int = 0
    gfw_available: bool = False
    gfw_requested: bool = False
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
    """Stage 1: optional SAR detection.

    ``available`` is set only once the provider has actually returned imagery
    we could run the detector over. Constructing ``SARDetector`` proves nothing
    about connectivity, so setting the flag there made a failed download
    indistinguishable from a clean scene.
    """
    out = {"detections": [], "available": False, "provider_reachable": False,
           "scenes_used": 0, "warnings": []}
    try:
        from engines.detection.sar_detector import SARDetector
        det = SARDetector()
        products = det.search_products(lon, lat, date, product_type="GRD", limit=max_products)
        # The catalogue query returned without raising, so the provider is up.
        out["provider_reachable"] = True
        if not products:
            # A 12-day revisit orbit can easily miss the exact incident day.
            # Widen to a ~7-day window (operationally: the slick may be
            # imaged up to a few days before/after the reported sighting).
            from datetime import datetime as _dt, timedelta as _td
            try:
                day = _dt.strptime(date, "%Y-%m-%d")
                products = det.search_near_date_range(
                    lon, lat,
                    (day - _td(days=3)).strftime("%Y-%m-%d"),
                    (day + _td(days=3)).strftime("%Y-%m-%d"),
                    product_type="GRD", limit=max_products,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"SAR: widened search failed: {e}")
        if not products:
            out["warnings"].append(
                "SAR: provider reachable but no Sentinel-1 product covers this date/location"
            )
            return out
        product = products[0]
        scene_date = (product.get("start") or "")[:10] or date
        out["warnings"].append(
            f"SAR: using Sentinel-1 scene {product['name']} acquired {scene_date} "
            f"(searched past {scene_date} for the incident of {date})"
        )
        logger.info(f"SAR: downloading {product['name']}")
        dl_dir = det.download_product(product["id"])
        detections = det.detect_from_product(str(dl_dir), band=band)
        out["detections"] = detections
        out["scenes_used"] = 1
        out["available"] = True
        if not detections:
            out["warnings"].append(
                "SAR: scene processed, detector found no dark-spot candidates"
            )
    except Exception as e:
        out["warnings"].append(f"SAR detection FAILED: {type(e).__name__}: {e}")
    return out


def _run_characterization(detections, **kw):
    if not detections:
        return None
    res = characterize_detections(detections, **kw)
    return res.__dict__


def _run_aging(detections, metocean_file, lon, lat, time, window_hours=48, scenes_used=1):
    """Estimate the age of a detected slick using SAR contrast + wind forcing.

    ``scenes_used`` is the number of distinct SAR acquisitions the detections
    came from. It must NOT be the detection count: several dark spots in one
    image are not several passes, and the age estimator widens or narrows its
    interval based on how many independent observations it believes it has.
    """
    from engines.aging.oil_age import estimate_oil_age, extract_mean_wind
    mean_wind = None
    wind_warning = None
    try:
        mean_wind = extract_mean_wind(metocean_file, lon, lat, time, window_hours)
    except Exception as e:
        wind_warning = f"Wind extraction for age failed: {type(e).__name__}: {e}"
        logger.warning(wind_warning)
    res = estimate_oil_age(detections, mean_wind_ms=mean_wind, frames=max(1, int(scenes_used)))
    out = res.__dict__
    out["warnings"] = [w for w in out["warnings"] if w]
    if wind_warning:
        out["warnings"].append(wind_warning)
    out["scenes_used"] = int(scenes_used)
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
        return None, None, 0, 0
    origin = tracker.compute_origin_probability(particles)
    num_launched = 100  # default ensemble size used by track_backward
    return origin, tracker, len(particles), num_launched


def _run_ais(origin, detection_time, duration_hours):
    """Stage 5: GFW vessels in origin bbox + optional registry enrichment.

    The GFW 4Wings presence report already embeds identity fields (name, MMSI,
    flag, vessel type, geartype) alongside AIS presence positions, so the
    suspects are built directly from it. The /vessels/{id} identity endpoint
    requires a separate dataset permission some tokens lack (403); enrichment
    is therefore best-effort and never blocks attribution.

    Returns ``(suspects, available, warnings)``. ``available`` means the report
    call succeeded — it is not set from a successful constructor, because an
    auth failure would otherwise be reported as "no vessels near the origin",
    which reads as exculpatory evidence rather than as an infrastructure error.
    """
    suspects = []
    available = False
    warnings = []
    try:
        from engines.ais.gfw_client import GFWClient
        from datetime import datetime, timedelta

        gfw = GFWClient()
        detection_dt = datetime.fromisoformat(detection_time)

        # GFW AIS coverage is reliable from ~2017 onward.
        if detection_dt.year < 2017:
            warnings.append(
                f"AIS: GFW coverage begins ~2017; incident year {detection_dt.year} "
                "is outside coverage, so no vessel search was performed"
            )
            return suspects, available, warnings

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
        # The report call returned, so AIS really was consulted.
        available = True
        if not raw:
            warnings.append(
                "AIS: GFW returned no vessel presence records for this box and window"
            )

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

            # A vessel with no reported mean position must stay unlocated.
            # Substituting the centre of the search box put it within a few
            # hundred metres of the origin centroid and earned it a near-maximal
            # proximity score on the heaviest attribution factor.
            avg_lat = mp.get("lat")
            avg_lon = mp.get("lon")
            position_known = avg_lat is not None and avg_lon is not None

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
                "avg_lat": avg_lat,
                "avg_lon": avg_lon,
                "position_known": position_known,
                # GFW presence is reported on a gridded product, so a position
                # locates a cell (~0.1 deg, order 10 km) and not the hull.
                "position_source": "gfw_presence_grid" if position_known else "none",
                "positions": entry.get("positions", []),
            })

        unlocated = sum(1 for s in suspects if not s["position_known"])
        if unlocated:
            warnings.append(
                f"AIS: {unlocated} of {len(suspects)} vessels have no reported position; "
                "their proximity factor cannot be scored"
            )

        # Filter out irrelevant traffic and attach behavioural anomaly evidence.
        from engines.ais.behaviour import filter_and_enrich
        before = len(suspects)
        suspects = filter_and_enrich(suspects)
        logger.info(f"AIS: candidate reduction {before} -> {len(suspects)}")
    except Exception as e:
        # Do not swallow this. A 403 here previously produced an empty suspect
        # list with gfw_available=True and no warning at all.
        warnings.append(f"AIS stage FAILED: {type(e).__name__}: {e}")
        logger.warning(f"AIS stage failed: {e}")
    return suspects, available, warnings


def _run_attribution(suspects, origin_centroid, history=None, window_hours=24):
    ranker = AttributionRanker()
    cargo = {}
    for s in suspects:
        m = s.get("mmsi", 0)
        if m:
            cargo[m] = s.get("cargo_type", s.get("ship_type", "Unknown"))
    return ranker.rank_vessels(
        suspects, origin_centroid, cargo,
        history=history, window_hours=window_hours,
    )


def run_pipeline(
    lon: float,
    lat: float,
    detection_time: str,
    duration_hours: int = 48,
    incident_id: Optional[str] = None,
    run_sar: bool = False,
    sar_date: Optional[str] = None,
    progress_callback=None,
    suspect_history: Optional[Dict[int, Dict]] = None,
) -> PipelineOutput:
    """Execute the full 6-stage pipeline.

    ``progress_callback`` is an optional callable ``(stage_name: str,
    progress_percent: float)`` invoked at stage boundaries. It is a pure
    instrumentation hook used by the async job runner to persist progress;
    it does not alter any scientific computation.

    ``suspect_history`` is a map of MMSI -> {"count": int, "incidents":
    [case_number]} from real prior-attribution records (repeat-offender
    profiling). It is optional and never fabricated by the pipeline — if the
    caller has no history it is simply omitted from ranking.
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
        out.sar_requested = True
        sar_date = sar_date or detection_time[:10]
        _progress("detection", 5.0)
        det_res = _run_detection(lon, lat, sar_date)
        out.sar_available = det_res["available"]
        out.sar_scenes_used = det_res["scenes_used"]
        out.warnings += det_res["warnings"]
        out.detections = det_res["detections"]

        # Look-alike screening: rule out biogenic slicks / low-wind zones / other
        # false positives BEFORE attribution starts (Feature 2). Uses the real
        # metocean wind for the environmental gate.
        if out.detections:
            _progress("characterization", 8.0)
            from engines.detection.lookalike import screen_lookalikes
            from engines.aging.oil_age import extract_mean_wind
            mean_wind = None
            try:
                mean_wind = extract_mean_wind(
                    resolve_metocean_file(incident_id), lon, lat,
                    detection_time, window_hours)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Look-alike wind gate skipped: {e}")
            filtered = screen_lookalikes(out.detections, mean_wind_ms=mean_wind)
            out.detections = filtered["detections"]
            out.lookalike_filter = filtered["summary"]
            flagged = filtered["summary"].get("flagged", 0)
            if flagged:
                out.warnings.append(
                    f"Look-alike screening flagged {flagged} of "
                    f"{filtered['summary'].get('screened', 0)} dark-spot "
                    "candidate(s) as probable non-oil (biogenic/low-wind/artefact)")

        if out.detections:
            _progress("characterization", 12.0)
            out.characterization = _run_characterization(out.detections)
            logger.info(f"Characterization: volume={out.characterization['est_volume_m3']} m3")
    else:
        out.warnings.append(
            "SAR detection was not requested for this run, so no slick was observed. "
            "Origin and forecast below are propagated from the operator-entered "
            "coordinates, not from a detected slick."
        )

    # Stage 3 & 4: Metocean + Transport (backward origin + forward forecast)
    _progress("metocean", 22.0)
    metocean_file = resolve_metocean_file(incident_id)
    _progress("transport", 30.0)
    origin, tracker, n_particles, n_launched = _run_transport(metocean_file, lon, lat, detection_time, duration_hours)
    if not origin:
        out.status = "no_particles"
        out.warnings.append("No transport particles remained in data domain")
        _progress("transport", 100.0)
        return out
    out.origin_centroid = [float(c) for c in origin["centroid"]]
    out.origin_bbox = [float(b) for b in origin["bbox"]]
    # Carry the particle-cloud spread through instead of dropping it, so the
    # origin can be drawn as a region rather than implied to be a fix.
    out.origin_std_dev = origin.get("std_dev")
    # Probabilistic origin zone (Feature 7): an ensemble area with certainty,
    # not a single fraudulent point-fix.
    from engines.transport.origin_zone import build_origin_zone
    out.origin_zone = build_origin_zone(
        origin.get("centroid"), origin.get("std_dev"),
        particle_count=n_particles, particles_total=n_launched)
    _progress("transport", 55.0)

    # Stage 4b: Forward drift forecast (predict future flow of the slick)
    if tracker is not None:
        _progress("forecast", 60.0)
        out.forecast = _run_forward_forecast(tracker, lon, lat, detection_time, duration_hours)

    # Stage 2b: Oil-spill age estimation (needs SAR detections + metocean wind)
    if out.detections and metocean_file:
        _progress("aging", 66.0)
        out.age = _run_aging(out.detections, metocean_file, lon, lat, detection_time,
                             scenes_used=out.sar_scenes_used or 1)

    # Stage 1b: Sentinel-2 EO confirmation (optical, complements SAR)
    if run_sar:
        _progress("eo", 72.0)
        out.eo = _run_eo_detection(lon, lat, sar_date or detection_time)

    # Stage 5: AIS via GFW
    _progress("ais", 80.0)
    out.gfw_requested = True
    out.suspects, out.gfw_available, ais_warnings = _run_ais(origin, detection_time, duration_hours)
    out.warnings += ais_warnings

    # Stage 6: Attribution — present only the top-ranked candidates so the
    # workspace shows the most probable source vessels rather than every AIS
    # contact in the search box.
    TOP_SUSPECTS = 5
    if out.suspects:
        _progress("attribution", 92.0)
        # Dark-vessel / AIS-gap fusion (Feature 1): SAR dark spots with no
        # co-located AIS track become top candidates — the PS's "unattributable".
        from engines.attribution.dark_vessel import fuse_dark_vessels
        out.suspects = fuse_dark_vessels(
            out.suspects, out.detections,
            window_hours=duration_hours, incident_id=out.incident_id)
        out.suspects = _run_attribution(
            out.suspects, origin["centroid"],
            history=suspect_history, window_hours=duration_hours,
        )[:TOP_SUSPECTS]
        dark = [s for s in out.suspects if s.get("dark_vessel")]
        if dark:
            out.warnings.append(
                "Dark-vessel signal: at least one SAR dark spot has no matching "
                "AIS track and is ranked as a primary source candidate "
                "(AIS may be deliberately disabled).")

    _progress("attribution", 100.0)
    return out
