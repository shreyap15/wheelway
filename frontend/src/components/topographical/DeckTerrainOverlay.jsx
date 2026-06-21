import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import Map, {
  NavigationControl,
  useControl,
} from "react-map-gl/mapbox";
import { MapboxOverlay } from "@deck.gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";

import {
  createTopographicalLayerFactory,
  getRampTooltip,
} from "./topographicalLayers";
import {
  DEFAULT_MESH_OPTIONS,
  MOCK_GRID_4X4,
} from "./topographicalUtils";

const DEFAULT_VIEW_STATE = Object.freeze({
  longitude: MOCK_GRID_4X4.center[0],
  latitude: MOCK_GRID_4X4.center[1],
  zoom: 16.1,
  pitch: 56,
  bearing: -32,
});

const TERRAIN_SOURCE_ID =
  "wheelway-wedge-ramp-terrain-dem";

function AnimatedDeckOverlay({
  layerFactory,
  onHover,
}) {
  const overlay = useControl(
    () =>
      new MapboxOverlay({
        interleaved: true,
        layers: layerFactory(0),
        getTooltip: getRampTooltip,
        onHover,
      }),
  );

  useEffect(() => {
    let animationFrameId;
    let previousFrameTime = 0;
    const targetFrameIntervalMs = 1000 / 30;

    const animate = (timeMs) => {
      if (
        timeMs - previousFrameTime >=
        targetFrameIntervalMs
      ) {
        overlay.setProps({
          layers: layerFactory(timeMs),
        });
        previousFrameTime = timeMs;
      }

      animationFrameId =
        requestAnimationFrame(animate);
    };

    animationFrameId =
      requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [layerFactory, overlay]);

  return null;
}

/**
 * Main Mapbox + Deck.gl viewport for the wedge/ramp topographical system.
 *
 * No controlled `viewState` is used. Mapbox owns camera movement internally,
 * preventing React renders during pan, zoom, pitch, and bearing changes.
 */
function DeckTerrainOverlay({
  routeSegments = MOCK_GRID_4X4.routeSegments,
  meshOptions = DEFAULT_MESH_OPTIONS,
  initialViewState = DEFAULT_VIEW_STATE,
  className = "topographical-map-viewport",
  terrainExaggeration = 1.2,
  mapStyle = "mapbox://styles/mapbox/dark-v11",
}) {
  const mapRef = useRef(null);
  const token =
    import.meta.env.VITE_MAPBOX_ACCESS_TOKEN;

  const layerFactory = useMemo(
    () =>
      createTopographicalLayerFactory({
        routeSegments,
        meshOptions,
      }),
    [routeSegments, meshOptions],
  );

  const handleHover = useCallback(
    ({ object }) => {
      const map = mapRef.current?.getMap();
      if (!map) return;

      map.getCanvas().style.cursor = object
        ? "crosshair"
        : "grab";
    },
    [],
  );

  const handleLoad = useCallback(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;

    if (!map.getSource(TERRAIN_SOURCE_ID)) {
      map.addSource(TERRAIN_SOURCE_ID, {
        type: "raster-dem",
        url: "mapbox://mapbox.mapbox-terrain-dem-v1",
        tileSize: 512,
        maxzoom: 14,
      });
    }

    map.setTerrain({
      source: TERRAIN_SOURCE_ID,
      exaggeration: terrainExaggeration,
    });

    map.setFog({
      range: [0.8, 8],
      color: "#07111f",
      "high-color": "#0f172a",
      "space-color": "#020617",
      "horizon-blend": 0.08,
    });

    // Side-profile scan baseline. easeTo provides a smooth initial reveal.
    map.easeTo({
      pitch: Math.min(
        60,
        Math.max(45, initialViewState.pitch ?? 56),
      ),
      bearing: initialViewState.bearing ?? -32,
      duration: 900,
      essential: true,
    });

    map.dragRotate.enable();
    map.touchZoomRotate.enableRotation();
    map.getCanvas().style.cursor = "grab";
  }, [
    initialViewState.bearing,
    initialViewState.pitch,
    terrainExaggeration,
  ]);

  if (!token) {
    return (
      <div
        className={`topographical-token-missing ${className}`}
      >
        <div className="topographical-token-card">
          <h2>
            Mapbox token missing
          </h2>
          <p>
            Add VITE_MAPBOX_ACCESS_TOKEN to
            frontend/.env and restart Vite.
          </p>
        </div>
      </div>
    );
  }

  return (
    <section
      className={className}
      aria-label="WheelWay 3D topographical accessibility map"
    >
      <Map
        ref={mapRef}
        mapboxAccessToken={token}
        mapStyle={mapStyle}
        initialViewState={{
          ...initialViewState,
          pitch: Math.min(
            60,
            Math.max(
              45,
              initialViewState.pitch ?? 56,
            ),
          ),
        }}
        minPitch={45}
        maxPitch={70}
        minZoom={13}
        maxZoom={20}
        bearingSnap={2}
        pitchWithRotate
        dragRotate
        touchZoomRotate
        antialias
        reuseMaps
        attributionControl={false}
        onLoad={handleLoad}
        style={{
          width: "100%",
          height: "100%",
        }}
      >
        <AnimatedDeckOverlay
          layerFactory={layerFactory}
          onHover={handleHover}
        />

        <NavigationControl
          position="bottom-right"
          showCompass
          visualizePitch
        />
      </Map>
    </section>
  );
}

export default memo(DeckTerrainOverlay);
