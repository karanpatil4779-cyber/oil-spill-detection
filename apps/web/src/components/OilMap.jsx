import React, { useRef, useEffect } from "react";
import * as maplibregl from "maplibre-gl";

const DEFAULT_STYLE = "https://tiles.openfreemap.org/styles/liberty";

/**
 * Reusable vector map for the workspace panels.
 * Uses MapLibre GL with free OpenFreeMap tiles (no API key needed).
 *
 * Layers can be passed as GeoJSON features; the component renders:
 *  - fillPolygon: spill / origin / forecast uncertainty areas
 *  - lineString: median drift path
 *  - point: detection centroid / origin / vessel markers
 *
 * props:
 *  - features: [{ type: 'fill'|'line'|'point', geometry: {...},
 *                  color, id }]
 *  - center, initialZoom, height
 */
export default function OilMap({ features = [], center, initialZoom = 8, height = 300 }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: DEFAULT_STYLE,
      center: center || [72.8, 18.9],
      zoom: initialZoom,
      attributionControl: false,
    });

    mapRef.current = map;

    map.on("load", () => {
      // Global source + layers for each feature
      map.addSource("oil-features", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "oil-fill",
        type: "fill",
        source: "oil-features",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "fill-color": ["coalesce", ["get", "color"], "#3b82f6"],
          "fill-opacity": 0.28,
        },
      });

      map.addLayer({
        id: "oil-fill-outline",
        type: "line",
        source: "oil-features",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "line-color": ["coalesce", ["get", "color"], "#3b82f6"],
          "line-width": 2,
        },
      });

      map.addLayer({
        id: "oil-line",
        type: "line",
        source: "oil-features",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: {
          "line-color": ["coalesce", ["get", "color"], "#10b981"],
          "line-width": 3,
          "line-dasharray": [2, 2],
        },
      });

      map.addLayer({
        id: "oil-point",
        type: "circle",
        source: "oil-features",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": ["coalesce", ["get", "radius"], 7],
          "circle-color": ["coalesce", ["get", "color"], "#ef4444"],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      });

      // Update with initial features
      updateFeatures(features);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (mapRef.current && mapRef.current.isStyleLoaded()) {
      updateFeatures(features);
    }
  }, [features]);

  const updateFeatures = (feats) => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const source = map.getSource("oil-features");
    if (!source) return;
    source.setData({
      type: "FeatureCollection",
      features: feats,
    });
  };

  return (
    <div
      ref={containerRef}
      className="oil-map"
      style={{ height, width: "100%", borderRadius: 8, overflow: "hidden" }}
    />
  );
}
