import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AISFilter:
    """
    Filters AIS vessel tracks to identify ships that were present
    within a specific spatial window during a specific time window.
    """

    def __init__(self, tracks_data_path: str = None):
        """
        Initialize the filter with AIS tracks data.

        Args:
            tracks_data_path: Path to a CSV/JSON file containing vessel tracks.
                               Expected columns: [mmsi, timestamp, longitude, latitude, vessel_name]
        """
        self.tracks_data_path = tracks_data_path
        self.df_tracks = None
        if tracks_data_path:
            self.load_tracks()

    def load_tracks(self):
        """Load AIS tracks from the provided path."""
        try:
            if self.tracks_data_path.endswith('.csv'):
                self.df_tracks = pd.read_csv(self.tracks_data_path)
            elif self.tracks_data_path.endswith('.json'):
                self.df_tracks = pd.read_json(self.tracks_data_path)

            self.df_tracks['timestamp'] = pd.to_datetime(self.df_tracks['timestamp'])
            logger.info(f"Loaded {len(self.df_tracks)} AIS records.")
        except Exception as e:
            logger.error(f"Error loading AIS tracks: {e}")

    def filter_vessels(self,
                      bbox: List[float],
                      time_window: Tuple[str, str]) -> List[Dict]:
        """
        Filter vessels that passed through the origin bounding box.

        Args:
            bbox: [min_lon, min_lat, max_lon, max_lat]
            time_window: (start_time_iso, end_time_iso)

        Returns:
            A list of unique vessels that matched the criteria.
        """
        if self.df_tracks is None:
            logger.warning("No tracks data loaded. Using mock data for demonstration.")
            return self._get_mock_matches(bbox, time_window)

        start_t = pd.to_datetime(time_window[0])
        end_t = pd.to_datetime(time_window[1])
        min_lon, min_lat, max_lon, max_lat = bbox

        # Filter by time
        mask = (self.df_tracks['timestamp'] >= start_t) & (self.df_tracks['timestamp'] <= end_t)
        df_filtered = self.df_tracks[mask]

        # Filter by spatial window
        mask_space = (df_filtered['longitude'] >= min_lon) & \
                     (df_filtered['longitude'] <= max_lon) & \
                     (df_filtered['latitude'] >= min_lat) & \
                     (df_filtered['latitude'] <= max_lat)

        matches = df_filtered[mask_space]

        # Group by vessel (MMSI) to get unique suspects
        suspects = []
        for mmsi, group in matches.groupby('mmsi'):
            suspects.append({
                "mmsi": int(mmsi),
                "vessel_name": group['vessel_name'].iloc[0],
                "match_count": len(group),
                "last_seen": group['timestamp'].max().isoformat(),
                "avg_lat": group['latitude'].mean(),
                "avg_lon": group['longitude'].mean()
            })

        return suspects

    def _get_mock_matches(self, bbox, time_window) -> List[Dict]:
        """Returns simulated matches when no real data is present."""
        return [
            {
                "mmsi": 123456789,
                "vessel_name": "Suspect Tanker A",
                "match_count": 15,
                "last_seen": time_window[1],
                "avg_lat": (bbox[1] + bbox[3]) / 2,
                "avg_lon": (bbox[0] + bbox[2]) / 2
            },
            {
                "mmsi": 987654321,
                "vessel_name": "Cargo Ship B",
                "match_count": 3,
                "last_seen": time_window[1],
                "avg_lat": (bbox[1] + bbox[3]) / 2 + 0.01,
                "avg_lon": (bbox[0] + bbox[2]) / 2 + 0.01
            }
        ]
