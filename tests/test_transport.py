import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from engines.transport.lagrangian_tracker import LagrangianTracker

def test_transport():
    # Use the fully merged metocean archive (u10, v10, uo, vo) that was produced
    # by process_incident_data.py. Both currents AND wind are read from the
    # single merged file, so wind_file is omitted.
    merged_file = "data/processed/metocean/mt_jipro_neftis/final_metocean.nc"

    tracker = LagrangianTracker(merged_file)

    # MT Jipro Neftis: Mumbai Outer Anchorage, off Mumbai, 2018-01-30
    start_lon, start_lat = 72.80, 18.90
    start_time = "2018-01-30T12:00:00"
    duration = 24  # track back 24 hours

    print(f"Tracking backward from {start_lon}, {start_lat} at {start_time}...")
    particles = tracker.track_backward(start_lon, start_lat, start_time, duration)
    origin = tracker.compute_origin_probability(particles)

    print(f"Active particles kept: {len(particles)}")
    print(f"Estimated Origin Centroid: {origin['centroid']}")
    print(f"Bounding Box: {origin['bbox']}")

    # Sanity checks
    assert len(particles) > 0, "No particles remained within the data domain"
    assert all(-90 <= p[1] <= 90 for p in particles), "Invalid latitude produced"
    return origin

if __name__ == "__main__":
    test_transport()
