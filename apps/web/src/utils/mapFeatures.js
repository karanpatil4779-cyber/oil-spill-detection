/**
 * Build MapLibre GeoJSON features from pipeline result data.
 * Returns an array of { id, type, geometry, color, radius } used by OilMap.
 */

function polygonFeature(lonLat4, color, id) {
  // bbox as [minLon, minLat, maxLon, maxLat]
  const [minLon, minLat, maxLon, maxLat] = lonLat4;
  return {
    id,
    type: "fill",
    color,
    geometry: {
      type: "Polygon",
      coordinates: [[
        [minLon, minLat], [maxLon, minLat], [maxLon, maxLat],
        [minLon, maxLat], [minLon, minLat],
      ]],
    },
  };
}

function lineFeature(coords, color, id) {
  return {
    id,
    type: "line",
    color,
    geometry: { type: "LineString", coordinates: coords },
  };
}

function pointFeature(lonLat, color, id, radius = 7) {
  return {
    id,
    type: "point",
    color,
    radius,
    geometry: { type: "Point", coordinates: lonLat },
  };
}

/**
 * Build the feature set for a workspace panel from a pipeline result.
 *
 * @param result pipeline_result (origin_centroid, origin_bbox, forecast, suspects, detections)
 * @param which which layers to include: 'detection' | 'origin' | 'forecast' | 'ais' | 'all'
 */
export function buildMapFeatures(result = {}, which = "all") {
  const features = [];

  const add = (f) => { if (f) features.push(f); };

  // Detection polygon (from characterization per_slick bbox_geo)
  if (which === "detection" || which === "all") {
    const perSlick = result.characterization?.per_slick || [];
    perSlick.forEach((s, i) => {
      if (s.bbox_geo?.length === 4) {
        add(polygonFeature(s.bbox_geo, "#ef4444", `slick-${i}`));
      }
    });
    // detection point = input location
    if (result.incident_id && result.origin_centroid) {
      add(pointFeature(result.origin_centroid, "#ef4444", "detection-point", 8));
    }
  }

  // Origin / hindcast uncertainty region
  if (which === "origin" || which === "all") {
    if (result.origin_bbox?.length === 4) {
      add(polygonFeature(result.origin_bbox, "#3b82f6", "origin-region"));
    }
    if (result.origin_centroid) {
      add(pointFeature(result.origin_centroid, "#3b82f6", "origin-centroid", 8));
    }
  }

  // Forecast forward cone
  if (which === "forecast" || which === "all") {
    if (result.forecast?.median_path?.length > 1) {
      add(lineFeature(result.forecast.median_path, "#10b981", "forecast-path"));
    }
    if (result.forecast?.bbox?.length === 4) {
      add(polygonFeature(result.forecast.bbox, "#10b981", "forecast-cone"));
    }
  }

  // AIS suspect vessels
  if (which === "ais" || which === "all") {
    (result.suspects || []).forEach((s, i) => {
      if (s.avg_lon != null && s.avg_lat != null) {
        add(pointFeature([s.avg_lon, s.avg_lat], "#f59e0b", `vessel-${i}`, 9));
      }
    });
  }

  return features;
}
