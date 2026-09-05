"""Evidence assessment: turn a pipeline result into an honest verdict.

Why this module exists
----------------------
``overall_confidence`` used to be the mean of two numbers that have nothing to
do with whether the target is oil:

  * ``age.confidence``      — a ladder of hardcoded constants in the age model
  * ``forecast.confidence`` — the fraction of transport particles that stayed
                              inside the current-field domain

Neither observes oil. A run in which the satellite was never contacted could
still score 1.0 and be rendered as "Likely oil spill" at maximum confidence.

This module separates the two questions that were conflated:

  1. *Is the target oil?*  -> ``detection_assessment()``, which scores only
     evidence that actually bears on the question, and returns ``None`` when
     there is none. Absence of evidence is reported as absence, never as zero
     and never as certainty.
  2. *How well constrained is the drift modelling?* ->
     ``transport_confidence()``, which is what the old number really measured
     and is now named accordingly.

Both are defensive about shape: every stage of the pipeline can legitimately be
``None``, and ``dict.get(key, {})`` does NOT protect against a key that exists
with a ``None`` value — that specific mistake made one endpoint raise
``AttributeError`` on every call.
"""

from typing import Dict, Optional

# The four decision strings. These are the only labels the platform may emit.
LIKELY_SPILL = "Likely oil spill"
PROBABLE_SPILL = "Probable oil spill"
UNCERTAIN = "Uncertain / review required"
LIKELY_FALSE = "Likely false detection"

# Relative weight of each piece of oil-bearing evidence. Weights are applied
# only over the factors that are actually available, so a missing factor
# withholds influence instead of contributing a silent zero.
_EVIDENCE_WEIGHTS = {
    "sar_detection": 0.40,
    "optical_confirmation": 0.30,
    "volume_plausible": 0.20,
    "age_plausible": 0.10,
}


def _d(value) -> Dict:
    """Return ``value`` if it is a dict, else an empty dict.

    ``result.get("age", {})`` returns ``None`` when the key is present with a
    ``None`` value, so the default never applies. This helper is the guard.
    """
    return value if isinstance(value, dict) else {}


def transport_confidence(result: Dict) -> Optional[float]:
    """Confidence in the drift modelling only — NOT evidence of oil.

    This is the quantity the old ``overall_confidence`` actually measured.
    """
    age = _d(result.get("age"))
    forecast = _d(result.get("forecast"))
    c1, c2 = age.get("confidence"), forecast.get("confidence")
    pair = [c for c in (c1, c2) if isinstance(c, (int, float))]
    if not pair:
        return None
    return round(sum(pair) / len(pair), 3)


def detection_assessment(result: Dict) -> Dict:
    """Assess whether the target is oil, using only oil-bearing evidence.

    Returns a dict with:
      ``label``       one of the four decision strings
      ``confidence``  float in [0, 1], or ``None`` when no evidence exists
      ``basis``       per-factor detail, including factors marked unavailable
      ``reasons``     plain-language statements shown to the analyst
      ``assessable``  False when the verdict rests on no evidence at all
    """
    detections = result.get("detections") or []
    characterization = _d(result.get("characterization"))
    eo = _d(result.get("eo"))
    age = _d(result.get("age"))

    sar_requested = bool(result.get("sar_requested", False))
    basis: Dict[str, Dict] = {}
    reasons = []

    # --- Factor 1: a SAR dark-spot detection exists at all -----------------
    if not sar_requested:
        basis["sar_detection"] = {"available": False,
                                  "reason": "SAR detection was not requested for this run"}
        reasons.append("No SAR detection was performed, so no slick was observed.")
    elif detections:
        basis["sar_detection"] = {"available": True, "value": 1.0,
                                  "detail": f"{len(detections)} dark-spot candidate(s)"}
    else:
        basis["sar_detection"] = {"available": True, "value": 0.0,
                                  "detail": "SAR ran and found no dark-spot candidates"}
        reasons.append("SAR imagery was processed and contained no dark-spot candidates.")

    # --- Factor 2: independent optical confirmation ------------------------
    if eo.get("available") and eo.get("confirmed") is not None:
        confirmed = bool(eo.get("confirmed"))
        basis["optical_confirmation"] = {
            "available": True, "value": 1.0 if confirmed else 0.0,
            "detail": "Sentinel-2 optical " + ("confirms" if confirmed else "does not confirm"),
        }
        if not confirmed:
            reasons.append("Optical imagery did not confirm the SAR candidate.")
    else:
        basis["optical_confirmation"] = {
            "available": False,
            "reason": eo.get("reason") or "no optical cross-check available",
        }

    # --- Factor 3: estimated volume is physically plausible ---------------
    oil_type = str(characterization.get("likely_oil_type") or "")
    if characterization:
        implausible = "FLAG" in oil_type or "implausibly large" in oil_type
        basis["volume_plausible"] = {
            "available": True, "value": 0.0 if implausible else 1.0,
            "detail": "flagged as implausibly large (look-alike risk)" if implausible
                      else "within a plausible range for a real slick",
        }
        if implausible:
            reasons.append("Estimated volume is implausibly large, which is "
                           "characteristic of a look-alike dark patch.")
    else:
        basis["volume_plausible"] = {"available": False,
                                     "reason": "characterisation did not run"}

    # --- Factor 4: estimated age is plausible ----------------------------
    age_hours = age.get("age_hours")
    if isinstance(age_hours, (int, float)) and age_hours == age_hours:  # not NaN
        ok = 0.0 < age_hours <= 96.0
        basis["age_plausible"] = {
            "available": True, "value": 1.0 if ok else 0.0,
            "detail": f"estimated age {age_hours:.1f} h",
        }
        if not ok:
            reasons.append(f"Estimated slick age of {age_hours:.1f} h is outside "
                           "the range in which a surface slick usually remains detectable.")
    else:
        basis["age_plausible"] = {"available": False,
                                  "reason": "age estimate unavailable"}

    # --- Combine over available factors only -----------------------------
    avail = {k: v for k, v in basis.items() if v.get("available")}
    if not avail:
        return {
            "label": UNCERTAIN,
            "confidence": None,
            "assessable": False,
            "basis": basis,
            "reasons": reasons or ["No evidence bearing on the presence of oil is available."],
            "factors_available": 0,
            "factors_total": len(_EVIDENCE_WEIGHTS),
        }

    wsum = sum(_EVIDENCE_WEIGHTS[k] for k in avail)
    score = sum(_EVIDENCE_WEIGHTS[k] * float(v["value"]) for k, v in avail.items()) / wsum
    score = round(score, 3)

    # A verdict resting on a single weak factor should not read as confident.
    if len(avail) == 1 and score >= 0.5:
        label = UNCERTAIN
        reasons.append("Only one line of evidence is available, which is not "
                       "sufficient to support a positive determination.")
    elif score >= 0.75:
        label = LIKELY_SPILL
    elif score >= 0.50:
        label = PROBABLE_SPILL
    elif score >= 0.25:
        label = UNCERTAIN
    else:
        label = LIKELY_FALSE

    return {
        "label": label,
        "confidence": score,
        "assessable": True,
        "basis": basis,
        "reasons": reasons,
        "factors_available": len(avail),
        "factors_total": len(_EVIDENCE_WEIGHTS),
    }


def summarize(result: Dict) -> Dict:
    """Attach both assessments to a pipeline result dict (in place) and return it."""
    if not isinstance(result, dict):
        return result
    result["detection_assessment"] = detection_assessment(result)
    result["transport_age_confidence"] = transport_confidence(result)
    return result


def stored_confidence(result: Dict) -> Optional[float]:
    """The value to persist in ``Case.overall_confidence``.

    Deliberately the *detection* confidence, so the column means "how likely is
    this oil". It is ``None`` when nothing bears on that question — a null is
    honest, whereas the previous behaviour stored a transport number that read
    as certainty about oil.
    """
    return detection_assessment(result).get("confidence")
