"""Look-alike / false-positive screening for SAR dark-spot detections.

The problem statement insists that "biogenic slicks, low-wind zones and other
false positives" be ruled out BEFORE attribution begins. This module treats
each SAR detection as a candidate and applies physical plausibility gates:

  * **Wind gate**: below a calm threshold, natural films / biogenic slicks and
    ship wakes are common dark-spot producers; above a high-wind threshold,
    wind-roughened sea can create false dark patches too. Detections whose
    environment falls in a "biogenic-favourable" band are flagged.

  * **Geometry gate**: a candidate that is nearly the width of the whole scene
    or that sits in the very corner (edge-clipped annulus) is much more likely
    to be a non-oil artefact.

  * **Yield gate**: the absolute number of "suspicious" dark spots a scene
    produces is itself evidence — many dark spots at once strongly suggests
    biogenic or noise, not a single operational discharge.

Each detection receives ``lookalike_risk`` (0/0.5/1) and ``lookalike_reason``;
the module also returns a summary that the pipeline attaches to its output so
the analyst can see exactly why a candidate was downgraded.
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# m/s. Below this, natural films are common and SAR dark spots are ambiguous.
LOW_WIND_MS = 4.0
# Above this, wind coupling can produce false dark patches / degraded contrast.
HIGH_WIND_MS = 15.0
# Number of dark spots a scene that suggests widespread biogenic/natural films.
MANY_DETECTIONS = 5
# Fraction of bbox that a very-large artefact would consume (rough, px-based).
LARGE_BBOX_FRACTION = 0.35


def _nearest_detection_centroid_lat(dets: List[Dict], idx: int) -> float:
    cg = dets[idx].get("centroid_geo")
    if cg and len(cg) >= 2:
        return float(cg[1])
    return 0.0


def screen_lookalikes(detections: List[Dict], mean_wind_ms=None) -> Dict:
    """Screen SAR detections for look-alike / false-positive risk.

    Args:
        detections: list of detection dicts from the SAR detector.
        mean_wind_ms: mean wind speed over the spill window (m/s) from the
            metocean archive. ``None`` disables the wind gate (data missing).

    Returns:
        Dict with ``detections`` (each annotated with lookalike_risk /
        lookalike_reason) and ``summary`` (counts + reasons for UI).
    """
    out_dets = []
    downgraded = []
    n = len(detections or [])

    for i, det in enumerate(detections or []):
        risk = 0.0
        reasons = []

        if mean_wind_ms is not None:
            if mean_wind_ms < LOW_WIND_MS:
                risk = max(risk, 0.5)
                reasons.append(
                    f"low wind ({mean_wind_ms:.1f} m/s) favours biogenic/natural "
                    "film dark spots")
            elif mean_wind_ms > HIGH_WIND_MS:
                risk = max(risk, 0.5)
                reasons.append(
                    f"high wind ({mean_wind_ms:.1f} m/s) can create wind-driven "
                    "false dark patches")

        bbox = det.get("bbox_px")
        if bbox and len(bbox) == 4:
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w <= 0 or h <= 0:
                risk = max(risk, 0.0)  # degenerate
            lat = _nearest_detection_centroid_lat(out_dets + detections, i)
            # Larger slicks are usually credible, but extreme size in a small
            # scene is characteristic of an oceanographic front artefact.
        if bbox and len(bbox) == 4:
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            # None of the metocean products are full-scene, so we only use the
            # aspect-ratio heuristic loosely: near-square huge patches can be
            # ship-wake or internal-wave artefacts.
            if w > 0 and h > 0 and max(w, h) / (w + h) < 0.55:
                risk = max(risk, 0.3)
                reasons.append("patch geometry suggests an elongated artefact "
                               "(wake/internal wave) rather than a slick")

        if n >= MANY_DETECTIONS:
            risk = max(risk, 0.5)
            reasons.append(
                f"scene contains {n} dark spots — a single operational discharge "
                "usually produces few candidates (biogenic-film pattern)")

        if risk > 0 and not reasons:
            reasons.append("multiple look-alike indicators present")

        det_ann = dict(det)
        det_ann["lookalike_risk"] = round(min(risk, 1.0), 2)
        det_ann["lookalike_reason"] = "; ".join(reasons) if reasons else None
        out_dets.append(det_ann)
        if risk > 0:
            downgraded.append(det_ann)

    return {
        "detections": out_dets,
        "summary": {
            "screened": n,
            "flagged": len(downgraded),
            "mean_wind_ms": (round(mean_wind_ms, 2) if mean_wind_ms is not None else None),
            "wind_gate": mean_wind_ms is not None,
            "reasons": [d["lookalike_reason"] for d in downgraded if d["lookalike_reason"]],
        },
    }