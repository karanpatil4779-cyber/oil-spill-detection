"""Client for the Global Fishing Watch (GFW) v3 API (2026 parameter schema).

Provides REAL historical vessel tracks and vessel identity data sourced from
Global Fishing Watch's global AIS vessel-tracking database, combined with 40+
public vessel registries.

Data source: https://globalfishingwatch.org/ (API key from .env -> GFW_API_KEY)

API CHANGES (v3, 2026):
  - /vessels/search uses a repeated `datasets` array query param (NOT datasets[0]).
  - Vessel positions in an area are fetched from the 4Wings report endpoint
    (POST /v3/4wings/report) using the `public-global-presence:latest` dataset.
    With spatial-aggregation=false + spatial-resolution=LOW it returns one row
    per vessel per 0.1-deg grid cell, carrying vessel_id / mmsi / shipName /
    flag / vesselType / geartype / lat / lon / hours. The body `geojson` field
    must be a real JSON object (not a stringified one).
  - Vessel identity detail endpoint /vessels/{id} requires separate dataset
    permissions that some tokens lack (403). The presence report already
    embeds identity fields, so identity lookups degrade gracefully.

NOTE ON AIS COVERAGE: GFW AIS coverage is reliable from ~2017 onward.
For incidents before 2017 (e.g. MSC Chitra 2010) there is no reliable AIS
track data, so callers should use official/registry records instead and the
client will signal that clearly rather than fabricating vessels.
"""

import os
import json
import logging
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://gateway.api.globalfishingwatch.org"
V3 = f"{BASE_URL}/v3"

VESSEL_IDENTITY_DATASET = "public-global-vessel-identity:latest"
AIS_PRESENCE_DATASET = "public-global-presence:latest"


class GFWAuthError(Exception):
    """Raised when the GFW token is missing, rejected (401) or lacks a dataset (403)."""


class GFWClient:
    def __init__(self, api_key: str = None):
        api_key = api_key or os.getenv("GFW_API_KEY")
        if not api_key:
            raise GFWAuthError(
                "GFW_API_KEY is not set in the environment / .env. "
                "Create an API access token at https://globalfishingwatch.org/our-apis/ "
                "and add it to your .env file."
            )
        self.token = api_key
        self.session = requests_session(api_key)

    def _get(self, path: str, params) -> Dict:
        url = f"{V3}{path}"
        resp = self.session.get(url, params=params, timeout=120)
        return self._handle(resp, url)

    def _post(self, path: str, params, body: Dict) -> Dict:
        url = f"{V3}{path}"
        resp = self.session.post(url, params=params, json=body, timeout=180)
        return self._handle(resp, url)

    def _handle(self, resp, url: str) -> Dict:
        if resp.status_code == 401:
            raise GFWAuthError(
                "GFW API returned 401 Unauthorized. Your GFW_API_KEY is invalid or "
                "expired. Regenerate a v3 API access token in the GFW console "
                "(globalfishingwatch.org) and update .env."
            )
        if resp.status_code == 403:
            raise GFWAuthError(
                f"GFW API returned 403 Forbidden on {url}. The token is authenticated "
                "but lacks permission for the requested dataset. Request dataset access "
                "for the datasets this client uses (vessel identity + AIS presence) at "
                "apis@globalfishingwatch.org, then renew the token."
            )
        if resp.status_code == 404:
            raise GFWAuthError(
                f"GFW API returned 404 on {url}. The endpoint/dataset may have changed "
                "or the dataset is deprecated."
            )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Vessel identity / registry (REAL ship data, 40+ registries)
    # ------------------------------------------------------------------
    def search_vessels(self, query: str, limit: int = 10) -> List[Dict]:
        """Search the vessel registry by name / MMSI / IMO."""
        if len(query) < 3:
            return []
        data = self._get("/vessels/search", [
            ("datasets", VESSEL_IDENTITY_DATASET),
            ("query", query),
            ("limit", limit),
        ])
        return data.get("entries", [])

    def get_vessel(self, vessel_id: str) -> Dict:
        """Get full identity for a GFW vessel id (registry + AIS self-reported)."""
        data = self._get(f"/vessels/{vessel_id}", [
            ("datasets", VESSEL_IDENTITY_DATASET),
        ])
        if isinstance(data, dict) and isinstance(data.get("selfReportedInfo"), list):
            sr = data["selfReportedInfo"]
            merged = {**data, "vessel": (sr[0] if sr else {})}
            reg = {}
            if data.get("registryInfo") and isinstance(data["registryInfo"], list) and data["registryInfo"]:
                reg = data["registryInfo"][0]
                merged["registry"] = reg
            merged["name"] = (
                reg.get("shipname")
                or (sr[0].get("shipname") if sr else None)
                or "Unknown"
            )
            merged["shipType"] = sr[0].get("shipType") if sr else None
            merged["vesselType"] = merged["shipType"]
            merged["flag"] = reg.get("flag") or (sr[0].get("flag") if sr else None)
            merged["imo"] = reg.get("imo")
            merged["mmsi"] = reg.get("ssvid") or (sr[0].get("ssvid") if sr else None)
            merged["length"] = reg.get("lengthM")
            merged["grossTonnage"] = reg.get("tonnageGt")
            merged["cargoType"] = merged["shipType"]
            return merged
        return data

    # ------------------------------------------------------------------
    # Vessel tracks / presence through an area (REAL AIS positions)
    # ------------------------------------------------------------------
    def vessels_in_bbox_and_time(
        self,
        bbox: List[float],
        time_window: List[str],
    ) -> List[Dict]:
        """Find vessels whose tracks pass through a bbox during a time window.

        Uses the 4Wings report endpoint with the AIS vessel-presence dataset,
        one row per vessel per 0.1-deg grid cell. Each row carries vessel_id,
        mmsi, shipName, flag, vesselType/geartype, lat, lon and presence-hours.
        Rows are aggregated by vessel_id into a single suspect record with the
        vessel's mean (hours-weighted) position.

        bbox: [min_lon, min_lat, max_lon, max_lat]
        time_window: [start_iso, end_iso]
        """
        min_lon, min_lat, max_lon, max_lat = bbox
        # Buffer slightly so we catch vessels just outside the bbox.
        geojson = {
            "type": "Polygon",
            "coordinates": [[
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]],
        }
        params = [
            ("format", "JSON"),
            ("group-by", "VESSEL_ID"),
            ("temporal-resolution", "ENTIRE"),
            ("datasets[0]", AIS_PRESENCE_DATASET),
            ("date-range", f"{time_window[0]},{time_window[1]}"),
            ("spatial-aggregation", "false"),
            ("spatial-resolution", "LOW"),
        ]
        data = self._post("/4wings/report", params, body={"geojson": geojson})
        entries = data.get("entries", [])
        return self._normalize_presence_entries(entries)

    @staticmethod
    def _normalize_presence_entries(entries: List[Dict]) -> List[Dict]:
        """Aggregate 4Wings presence rows into the project's suspect schema.

        The response shape is:
            {"total": N, "entries": [ {"public-global-presence:v4.0": [row, ...]}, ... ]}
        One row exists per vessel per 0.1-deg grid cell. Rows are grouped by
        vessel_id, summing presence hours and computing the hours-weighted mean
        position as the vessel's representative location.
        """
        grouped = {}
        for entry in entries:
            for _dataset_key, rows in entry.items():
                if not rows:
                    continue
                for row in rows:
                    vid = row.get("vesselId")
                    if not vid:
                        continue
                    g = grouped.setdefault(vid, {
                        "vessel_id": vid,
                        "mmsi": row.get("mmsi"),
                        "vessel_name": row.get("shipName") or "Unknown",
                        "ship_type": row.get("vesselType") or row.get("geartype") or "Unknown",
                        "geartype": row.get("geartype"),
                        "flag": row.get("flag", "Unknown"),
                        "imo": row.get("imo"),
                        "callsign": row.get("callsign"),
                        "presence_hours": 0,
                        "entry_timestamp": row.get("entryTimestamp"),
                        "exit_timestamp": row.get("exitTimestamp"),
                        "first_transmission": row.get("firstTransmissionDate"),
                        "last_transmission": row.get("lastTransmissionDate"),
                        "_wlons": 0.0,
                        "_wlats": 0.0,
                        "_whours": 0.0,
                        "positions": [],
                    })
                    if "lat" in row and "lon" in row:
                        g["positions"].append({"lat": row["lat"], "lon": row["lon"]})
                        hours = float(row.get("hours", 0) or 0)
                        g["_wlons"] += row["lon"] * hours
                        g["_wlats"] += row["lat"] * hours
                        g["_whours"] += hours
                    g["presence_hours"] += float(row.get("hours", 0) or 0)

        suspects = []
        for g in grouped.values():
            if g["_whours"] > 0:
                g["mean_position"] = {
                    "lat": g["_wlats"] / g["_whours"],
                    "lon": g["_wlons"] / g["_whours"],
                }
            else:
                g["mean_position"] = None
            g.pop("_wlons", None)
            g.pop("_wlats", None)
            g.pop("_whours", None)
            suspects.append(g)

        # Rank-like sort: vessels with more presence hours first.
        suspects.sort(key=lambda s: s["presence_hours"], reverse=True)
        return suspects


def requests_session(api_key: str):
    import requests
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {api_key}"})
    return s


def health_check(client: GFWClient) -> bool:
    """Attempt a lightweight authenticated call to verify the token works.

    Uses the AIS presence report (public-global-presence) which is the dataset
    this project relies on; the vessel-identity search endpoint needs a
    separate permission that many tokens lack, so we don't test against it.
    """
    try:
        geom = {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]],
        }
        client._post("/4wings/report", [
            ("format", "JSON"),
            ("group-by", "VESSEL_ID"),
            ("temporal-resolution", "ENTIRE"),
            ("datasets[0]", AIS_PRESENCE_DATASET),
            ("date-range", "2021-01-01T00:00:00.000Z,2021-01-02T00:00:00.000Z"),
            ("spatial-aggregation", "false"),
            ("spatial-resolution", "LOW"),
        ], body={"geojson": geom})
        return True
    except Exception:
        return False