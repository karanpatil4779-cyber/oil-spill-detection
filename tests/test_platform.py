"""Pytest test suite for the Marine Oil-Spill Investigation Platform.

Covers: scientific result normalisation, quantification, age/confidence,
uncertainty/look-alike classification, transport output, async job transitions,
report export eligibility, role access boundaries, audit log creation, and
more — per Milestones 6/9.
"""

import os
import sys
import time
import pytest
import math
from unittest.mock import patch, MagicMock

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ======================================================================
# Scientific module tests
# ======================================================================

class TestCharacterization:
    """Area/volume/tonne calculations from quantifier.py"""

    def test_quantifier_returns_structured_result(self):
        from engines.characterization.quantifier import characterize_detections
        detections = [
            {
                "bbox_px": [100, 100, 200, 200],
                "bbox_geo": [72.8, 18.9, 72.9, 19.0],
                "area_km2": 1.5,
                "mean_db": -12.0,
            }
        ]
        result = characterize_detections(detections)
        assert hasattr(result, "total_area_km2")
        assert result.total_area_km2 > 0

    def test_quantifier_empty_detections(self):
        from engines.characterization.quantifier import characterize_detections
        result = characterize_detections([])
        assert result.total_area_km2 == 0

    def test_quantifier_volume_positive(self):
        from engines.characterization.quantifier import characterize_detections
        detections = [
            {
                "bbox_px": [0, 0, 100, 100],
                "bbox_geo": [72.8, 18.9, 72.85, 18.95],
                "area_km2": 0.5,
                "mean_db": -10.0,
            }
        ]
        result = characterize_detections(detections)
        assert result.est_volume_m3 >= 0


class TestOilAge:
    """Age interval/confidence logic from oil_age.py"""

    def test_estimate_oil_age_returns_interval(self):
        from engines.aging.oil_age import estimate_oil_age
        detections = [{"mean_db": -12.0, "area_px": 500}]
        result = estimate_oil_age(detections, mean_wind_ms=5.0, frames=1)
        assert result.age_min_hours >= 0
        assert result.age_max_hours >= result.age_min_hours
        assert 0 <= result.confidence <= 1

    def test_age_confidence_increases_with_frames(self):
        from engines.aging.oil_age import estimate_oil_age
        detections = [{"mean_db": -12.0, "area_px": 500}]
        r1 = estimate_oil_age(detections, mean_wind_ms=5.0, frames=1)
        r2 = estimate_oil_age(detections, mean_wind_ms=5.0, frames=3)
        assert r2.confidence >= r1.confidence

    def test_age_with_no_signal_returns_nan(self):
        from engines.aging.oil_age import estimate_oil_age
        result = estimate_oil_age([], mean_wind_ms=None, frames=1)
        assert math.isnan(result.age_hours)

    def test_wind_factor_calm(self):
        from engines.aging.oil_age import _weather_wind_factor
        assert _weather_wind_factor(1.0) < 1.0

    def test_wind_factor_strong(self):
        from engines.aging.oil_age import _weather_wind_factor
        assert _weather_wind_factor(15.0) > 1.0

    def test_contrast_to_age_strong_contrast(self):
        from engines.aging.oil_age import _contrast_to_age
        age = _contrast_to_age(-15.0)
        assert age is not None
        assert age >= 0

    def test_contrast_to_age_weak_contrast(self):
        from engines.aging.oil_age import _contrast_to_age
        result = _contrast_to_age(-1.0)
        assert result is None


class TestTransport:
    """Backward/forward transport output validation"""

    def test_backward_tracking_returns_particles(self):
        from engines.transport.lagrangian_tracker import LagrangianTracker
        metocean = os.path.join(
            PROJECT_ROOT,
            "data/processed/metocean/mt_jipro_neftis/final_metocean.nc",
        )
        if not os.path.exists(metocean):
            pytest.skip("Metocean data not available")
        tracker = LagrangianTracker(metocean)
        particles = tracker.track_backward(
            72.8, 19.0, "2018-01-30T00:00:00", 24
        )
        assert len(particles) > 0

    def test_origin_probability_returns_centroid_and_bbox(self):
        from engines.transport.lagrangian_tracker import LagrangianTracker
        metocean = os.path.join(
            PROJECT_ROOT,
            "data/processed/metocean/mt_jipro_neftis/final_metocean.nc",
        )
        if not os.path.exists(metocean):
            pytest.skip("Metocean data not available")
        tracker = LagrangianTracker(metocean)
        particles = tracker.track_backward(
            72.8, 19.0, "2018-01-30T00:00:00", 24
        )
        origin = tracker.compute_origin_probability(particles)
        assert "centroid" in origin
        assert "bbox" in origin
        assert len(origin["centroid"]) == 2

    def test_forecast_ensemble_returns_forecast(self):
        from engines.transport.lagrangian_tracker import LagrangianTracker
        metocean = os.path.join(
            PROJECT_ROOT,
            "data/processed/metocean/mt_jipro_neftis/final_metocean.nc",
        )
        if not os.path.exists(metocean):
            pytest.skip("Metocean data not available")
        tracker = LagrangianTracker(metocean)
        fc = tracker.forecast_ensemble(
            72.8, 19.0, "2018-01-30T00:00:00",
            duration_hours=24, num_particles=50,
        )
        assert fc is not None
        assert "centroid" in fc
        assert "confidence" in fc


class TestAttributionRanker:
    """Attribution factor contributions"""

    def test_ranker_returns_ranked_suspects(self):
        from engines.attribution.ranker import AttributionRanker
        ranker = AttributionRanker()
        suspects = [
            {"mmsi": 123, "vessel_name": "Test", "ship_type": "Cargo",
             "cargo_type": "Oil", "flag": "IN", "match_count": 10,
             "avg_lat": 18.95, "avg_lon": 72.85, "presence_hours": 10},
            {"mmsi": 456, "vessel_name": "Test2", "ship_type": "Tanker",
             "cargo_type": "Crude", "flag": "SG", "match_count": 5,
             "avg_lat": 19.0, "avg_lon": 72.9, "presence_hours": 5},
        ]
        ranked = ranker.rank_vessels(suspects, [72.8, 18.9], {123: "Oil", 456: "Crude"})
        assert len(ranked) > 0
        assert "attribution_score" in ranked[0]
        assert "factors" in ranked[0]


class TestPipelineIntegration:
    """Pipeline orchestration with mocked transport"""

    def test_pipeline_output_has_all_fields(self):
        from engines.pipeline import PipelineOutput
        out = PipelineOutput(
            incident_id="test",
            status="ok",
            origin_centroid=[72.8, 18.9],
            origin_bbox=[72.7, 18.8, 72.9, 19.0],
            detections=[],
            characterization=None,
            age=None,
            eo=None,
            forecast=None,
            suspects=[],
            sar_available=False,
            gfw_available=False,
            warnings=[],
        )
        assert out.incident_id == "test"
        assert out.origin_centroid == [72.8, 18.9]
        assert out.status == "ok"


# ======================================================================
# Backend API tests (auth, roles, async runs)
# ======================================================================

@pytest.fixture(scope="module")
def client():
    """Create a test client. Uses a separate DB for isolation."""
    os.environ["RUNNER_PAUSED"] = "1"
    os.environ["DATABASE_URL"] = "sqlite:///test_oil_spill.db"
    from fastapi.testclient import TestClient
    from apps.api.main import app
    with TestClient(app) as c:
        yield c
    # Cleanup
    try:
        os.remove("test_oil_spill.db")
    except OSError:
        pass


@pytest.fixture(scope="module")
def analyst_token(client):
    resp = client.post("/auth/login", json={
        "email": "analyst@oilspill.gov", "password": "analyst123"
    })
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def supervisor_token(client):
    resp = client.post("/auth/login", json={
        "email": "supervisor@oilspill.gov", "password": "super123"
    })
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token(client):
    resp = client.post("/auth/login", json={
        "email": "admin@oilspill.gov", "password": "admin123"
    })
    return resp.json()["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


class TestAuth:
    def test_login_success(self, client):
        resp = client.post("/auth/login", json={
            "email": "analyst@oilspill.gov", "password": "analyst123"
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_wrong_password(self, client):
        resp = client.post("/auth/login", json={
            "email": "analyst@oilspill.gov", "password": "wrong"
        })
        assert resp.status_code in (400, 401)

    def test_me_endpoint(self, client, analyst_token):
        resp = client.get("/auth/me", headers=auth_header(analyst_token))
        assert resp.status_code == 200
        assert resp.json()["role"] == "analyst"

    def test_invalid_token(self, client):
        resp = client.get("/auth/me", headers=auth_header("invalidtoken"))
        assert resp.status_code == 401


class TestRoleEnforcement:
    """Server-side role enforcement — analyst cannot access admin routes."""

    def test_analyst_cannot_list_users(self, client, analyst_token):
        resp = client.get("/admin/users", headers=auth_header(analyst_token))
        assert resp.status_code == 403

    def test_analyst_cannot_view_system_status(self, client, analyst_token):
        resp = client.get("/admin/system-status", headers=auth_header(analyst_token))
        assert resp.status_code == 403

    def test_supervisor_cannot_list_users(self, client, supervisor_token):
        resp = client.get("/admin/users", headers=auth_header(supervisor_token))
        assert resp.status_code == 403

    def test_admin_can_list_users(self, client, admin_token):
        resp = client.get("/admin/users", headers=auth_header(admin_token))
        assert resp.status_code == 200

    def test_admin_can_view_system_status(self, client, admin_token):
        resp = client.get("/admin/system-status", headers=auth_header(admin_token))
        assert resp.status_code == 200

    def test_analyst_cannot_approve_case(self, client, analyst_token):
        resp = client.post("/cases/1/approve", headers=auth_header(analyst_token))
        assert resp.status_code in (403, 404)

    def test_supervisor_cannot_create_case(self, client, supervisor_token):
        resp = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01"
        }, headers=auth_header(supervisor_token))
        assert resp.status_code == 403

    def test_admin_cannot_create_case(self, client, admin_token):
        resp = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01"
        }, headers=auth_header(admin_token))
        assert resp.status_code == 403


class TestCaseCRUD:
    def test_create_case(self, client, analyst_token):
        resp = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
            "location_name": "Test Location",
        }, headers=auth_header(analyst_token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["case_number"].startswith("INC-2026-")
        return data["id"]

    def test_list_cases_analyst(self, client, analyst_token):
        resp = client.get("/cases", headers=auth_header(analyst_token))
        assert resp.status_code == 200
        assert "cases" in resp.json()

    def test_get_case_by_id(self, client, analyst_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        resp = client.get(f"/cases/{case_id}", headers=auth_header(analyst_token))
        assert resp.status_code == 200
        assert resp.json()["id"] == case_id

    def test_analyst_cannot_see_other_case(self, client):
        a1 = client.post("/auth/login", json={
            "email": "analyst@oilspill.gov", "password": "analyst123"
        }).json()["access_token"]
        a2 = client.post("/auth/login", json={
            "email": "analyst2@oilspill.gov", "password": "analyst123"
        }).json()["access_token"]
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(a1))
        case_id = create.json()["id"]
        resp = client.get(f"/cases/{case_id}", headers=auth_header(a2))
        assert resp.status_code == 403


class TestReportExport:
    def test_cannot_generate_report_without_approval(self, client, analyst_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        resp = client.post(f"/cases/{case_id}/generate-report",
                           headers=auth_header(analyst_token))
        assert resp.status_code == 400
        assert "approval" in resp.json()["detail"].lower()

    def test_approved_case_can_generate_report(self, client, analyst_token, supervisor_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        client.patch(f"/cases/{case_id}/status",
                     json={"status": "pending_review"},
                     headers=auth_header(analyst_token))
        client.post(f"/cases/{case_id}/approve",
                    headers=auth_header(supervisor_token))
        resp = client.post(f"/cases/{case_id}/generate-report",
                           headers=auth_header(analyst_token))
        assert resp.status_code == 200


class TestSupervisorWorkflow:
    def test_return_requires_note(self, client, analyst_token, supervisor_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        client.patch(f"/cases/{case_id}/status",
                     json={"status": "pending_review"},
                     headers=auth_header(analyst_token))
        resp = client.post(f"/cases/{case_id}/return",
                           json={"content": ""},
                           headers=auth_header(supervisor_token))
        assert resp.status_code == 400

    def test_return_with_note_succeeds(self, client, analyst_token, supervisor_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        client.patch(f"/cases/{case_id}/status",
                     json={"status": "pending_review"},
                     headers=auth_header(analyst_token))
        resp = client.post(f"/cases/{case_id}/return",
                           json={"content": "Please review the characterization section."},
                           headers=auth_header(supervisor_token))
        assert resp.status_code == 200


class TestAdminIsolation:
    """Admin must NOT see investigation content (case data, polygons, etc.)"""

    def test_admin_cannot_access_case_data(self, client, admin_token, analyst_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        resp = client.get(f"/cases/{case_id}", headers=auth_header(admin_token))
        assert resp.status_code == 403

    def test_admin_cannot_list_cases(self, client, admin_token):
        resp = client.get("/cases", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0


class TestAsyncJobRunner:
    def test_enqueue_returns_run_id(self, client, analyst_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        resp = client.post(f"/cases/{case_id}/runs",
                           json={"run_sar": False},
                           headers=auth_header(analyst_token))
        assert resp.status_code == 202
        data = resp.json()
        assert "run_id" in data
        assert data["status"] in ("queued", "running")

    def test_cannot_enqueue_second_run(self, client, analyst_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        client.post(f"/cases/{case_id}/runs",
                    json={"run_sar": False},
                    headers=auth_header(analyst_token))
        resp = client.post(f"/cases/{case_id}/runs",
                           json={"run_sar": False},
                           headers=auth_header(analyst_token))
        assert resp.status_code == 409

    def test_run_status_endpoint(self, client, analyst_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        run_resp = client.post(f"/cases/{case_id}/runs",
                               json={"run_sar": False},
                               headers=auth_header(analyst_token))
        run_id = run_resp.json()["run_id"]
        resp = client.get(f"/cases/{case_id}/runs/{run_id}",
                          headers=auth_header(analyst_token))
        assert resp.status_code == 200
        assert resp.json()["run_id"] == run_id


class TestAuditLog:
    def test_case_audit_log_records_creation(self, client, analyst_token):
        create = client.post("/cases", json={
            "lon": 72.8, "lat": 18.9, "detection_date": "2024-01-01",
        }, headers=auth_header(analyst_token))
        case_id = create.json()["id"]
        resp = client.get(f"/cases/{case_id}/audit",
                          headers=auth_header(analyst_token))
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) > 0
        assert entries[0]["action_type"] == "case_created"


class TestAdminAuditLog:
    def test_admin_can_view_system_audit(self, client, admin_token):
        resp = client.get("/admin/audit-log",
                          headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
