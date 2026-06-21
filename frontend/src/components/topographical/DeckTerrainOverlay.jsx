import { useEffect, useRef, useState } from "react";
import { MapboxOverlay } from "@deck.gl/mapbox";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { createTopographicalLayers } from "./topographicalLayers";
import { buildSampledRoute, flattenOrderedRoute, routeCenter } from "./topographicalUtils";

const DEFAULT_MAP_STYLE = "mapbox://styles/mapbox/standard";

function addTerrain(map) {
  if (!map.getSource("mapbox-dem")) {
    map.addSource("mapbox-dem", {
      type: "raster-dem",
      url: "mapbox://mapbox.mapbox-terrain-dem-v1",
      tileSize: 512,
      maxzoom: 14,
    });
  }

  map.setTerrain({
    source: "mapbox-dem",
    exaggeration: 1,
  });
}

function addBuildings(map) {
  if (map.getLayer("wheelway-3d-buildings") || !map.getSource("composite")) {
    return;
  }

  try {
    map.addLayer({
      id: "wheelway-3d-buildings",
      source: "composite",
      "source-layer": "building",
      filter: ["==", ["get", "extrude"], "true"],
      type: "fill-extrusion",
      minzoom: 14,
      paint: {
        "fill-extrusion-color": "#7f8f8a",
        "fill-extrusion-height": ["coalesce", ["get", "height"], 0],
        "fill-extrusion-base": ["coalesce", ["get", "min_height"], 0],
        "fill-extrusion-opacity": 0.58,
      },
    });
  } catch (error) {
    console.warn("Map style does not expose a compatible building layer.", error);
  }
}

function boundsForRoute(route) {
  if (!route.length) {
    return null;
  }

  return route.reduce(
    (bounds, point) => bounds.extend([point.longitude, point.latitude]),
    new mapboxgl.LngLatBounds(
      [route[0].longitude, route[0].latitude],
      [route[0].longitude, route[0].latitude],
    ),
  );
}

export default function DeckTerrainOverlay({
  routeSegments,
  sampledRoute,
  setSampledRoute,
  hoveredDistanceM,
  setHoveredDistanceM,
  mapboxAccessToken = import.meta.env.VITE_MAPBOX_TOKEN,
  mapStyle = DEFAULT_MAP_STYLE,
  ribbonWidthM = 1.8,
}) {
  const containerRef = useRef(null);
  const initialRouteSegmentsRef = useRef(routeSegments);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const hasMapboxToken = Boolean(mapboxAccessToken);

  useEffect(() => {
    if (!hasMapboxToken) {
      buildSampledRoute(routeSegments, null).then(setSampledRoute);
    }
  }, [hasMapboxToken, routeSegments, setSampledRoute]);

  useEffect(() => {
    if (!hasMapboxToken) {
      return;
    }

    if (!containerRef.current || mapRef.current) {
      return;
    }

    mapboxgl.accessToken = mapboxAccessToken;

    const initialRoute = flattenOrderedRoute(initialRouteSegmentsRef.current);
    const center = routeCenter(initialRoute);
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: mapStyle,
      center: [center.longitude, center.latitude],
      zoom: 16.2,
      pitch: 67,
      bearing: -28,
      antialias: true,
    });

    const overlay = new MapboxOverlay({
      interleaved: true,
      layers: [],
    });

    mapRef.current = map;
    overlayRef.current = overlay;
    map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(overlay);

    map.once("load", () => {
      addTerrain(map);
      addBuildings(map);
      setMapReady(true);
    });

    return () => {
      overlay.finalize();
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
      setMapReady(false);
    };
  }, [hasMapboxToken, mapStyle, mapboxAccessToken]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !hasMapboxToken) {
      return;
    }

    let isCancelled = false;

    async function sampleTerrain() {
      await new Promise((resolve) => {
        if (map.areTilesLoaded()) {
          resolve();
          return;
        }

        map.once("idle", resolve);
      });

      const samples = await buildSampledRoute(routeSegments, (point) =>
        map.queryTerrainElevation(
          {
            lng: point.longitude,
            lat: point.latitude,
          },
          {
            exaggerated: false,
          },
        ),
      );

      if (isCancelled) {
        return;
      }

      setSampledRoute(samples);

      const bounds = boundsForRoute(samples);
      if (bounds) {
        map.fitBounds(bounds, {
          padding: 120,
          duration: 900,
          maxZoom: 18,
        });
      }
    }

    sampleTerrain();

    return () => {
      isCancelled = true;
    };
  }, [hasMapboxToken, mapReady, routeSegments, setSampledRoute]);

  useEffect(() => {
    if (!overlayRef.current) {
      return;
    }

    overlayRef.current.setProps({
      layers: createTopographicalLayers({
        samples: sampledRoute,
        hoveredDistanceM,
        setHoveredDistanceM,
        ribbonWidthM,
      }),
    });
  }, [hoveredDistanceM, ribbonWidthM, sampledRoute, setHoveredDistanceM]);

  if (!hasMapboxToken) {
    return (
      <div className="topographical-map-fallback">
        <div>
          <p className="eyebrow">Mapbox token required</p>
          <h2>Terrain sampling paused</h2>
          <p>
            Set <code>VITE_MAPBOX_TOKEN</code> to render Mapbox terrain,
            buildings, and the Deck.gl route overlay.
          </p>
        </div>
      </div>
    );
  }

  return <div ref={containerRef} className="topographical-map-canvas" />;
}
