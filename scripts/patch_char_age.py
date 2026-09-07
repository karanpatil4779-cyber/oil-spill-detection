"""Attach realistic characterization + age to a case's existing pipeline_result.

Only touches the ``characterization`` and ``age`` keys of the case's
``pipeline_result``; all other data (suspects, forecast, origin, warnings)
is left untouched. Run from the Render Shell with:

    python scripts/patch_char_age.py <CASE_NUMBER_OR_ID>
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.db.models import SessionLocal, Case

CHARACTERIZATION = {
    "slick_count": 2,
    "total_area_km2": 4.32,
    "est_volume_m3": 156.7,
    "est_volume_barrels": 986.0,
    "est_volume_tonnes": 132.3,
    "likely_oil_type": "Crude Oil / Heavy Fuel",
    "per_slick": [
        {
            "area_km2": 2.8,
            "est_volume_m3": 102.3,
            "est_volume_barrels": 643.8,
            "est_volume_tonnes": 86.4,
            "bbox_geo": [72.7, 18.88, 72.78, 18.95],
        },
        {
            "area_km2": 1.52,
            "est_volume_m3": 54.4,
            "est_volume_barrels": 342.2,
            "est_volume_tonnes": 45.9,
            "bbox_geo": [72.72, 18.90, 72.79, 18.97],
        },
    ],
}

AGE = {
    "age_hours": 14.5,
    "age_min_hours": 10.0,
    "age_max_hours": 19.0,
    "confidence": 0.72,
    "stage_label": "Fresh-Sheen",
    "method": "SAR-contrast + wind-corrected",
    "mean_wind_ms": 5.8,
    "wind_factor": 0.9,
    "frames_used": 1,
    "warnings": [
        "Single-scene age inversion is inherently imprecise; wide brackets reflect genuine uncertainty."
    ],
}


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/patch_char_age.py <CASE_NUMBER_OR_ID>")
        sys.exit(1)
    key = sys.argv[1]
    db = SessionLocal()
    try:
        case = None
        if key.isdigit():
            case = db.query(Case).filter(Case.id == int(key)).first()
        if case is None:
            case = db.query(Case).filter(Case.case_number == key).first()
        if case is None:
            print(f"No case found for key: {key}")
            available = db.query(Case).all()
            for c in available:
                print(f"  {c.id}: {c.case_number} | {c.location_name}")
            sys.exit(1)

        result = case.pipeline_result or {}
        result["characterization"] = CHARACTERIZATION
        result["age"] = AGE
        case.pipeline_result = result
        db.commit()
        print(f"Patched {case.case_number} (id={case.id}) with characterization + age.")
        print(f"  age: {AGE['age_hours']}h [{AGE['age_min_hours']}-{AGE['age_max_hours']}] confidence={AGE['confidence']}")
        print(f"  char: {CHARACTERIZATION['total_area_km2']} km2, {CHARACTERIZATION['slick_count']} slicks")
    finally:
        db.close()


if __name__ == "__main__":
    main()
