import { PolygonLayer, ScatterplotLayer } from "@deck.gl/layers";
import {
  buildRibbonPolygons,
  coordinateAtRouteDistance,
  nearestRouteDistance,
} from "./topographicalUtils";

const ACCESSIBLE_COLOR = [68, 214, 118, 220];
const CAUTION_COLOR = [239, 181, 74, 230];
const BARRIER_COLOR = [232, 78, 78, 235];
const SIDE_COLOR = [26, 42, 36, 180];
const HOVER_COLOR = [85, 190, 255, 255];

function scoreForSample(sample) {
  return Number(
    sample.segment?.accessibility_score ??
      sample.segment?.accessibilityScore ??
      sample.segment?.score ??
      100,
  );
}

function colorForSample(sample) {
  const score = scoreForSample(sample);

  if (score >= 80) {
    return ACCESSIBLE_COLOR;
  }

  if (score >= 55) {
    return CAUTION_COLOR;
  }

  return BARRIER_COLOR;
}

export function createTopographicalLayers({
  samples,
  hoveredDistanceM,
  setHoveredDistanceM,
  ribbonWidthM = 1.8,
}) {
  const { top, sides } = buildRibbonPolygons(samples, ribbonWidthM);
  const cursorPoint = coordinateAtRouteDistance(samples, hoveredDistanceM);
  const layers = [
    new PolygonLayer({
      id: "sidewalk-ribbon-sides",
      data: sides,
      getPolygon: (cell) => cell.polygon,
      getFillColor: SIDE_COLOR,
      getLineColor: [255, 255, 255, 20],
      stroked: false,
      filled: true,
      extruded: false,
      parameters: {
        depthTest: true,
      },
    }),
    new PolygonLayer({
      id: "sidewalk-ribbon-top",
      data: top,
      getPolygon: (cell) => cell.polygon,
      getFillColor: (cell) => colorForSample(cell.sample),
      getLineColor: [255, 255, 255, 80],
      getLineWidth: 0.35,
      lineWidthUnits: "meters",
      stroked: true,
      filled: true,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 60],
      extruded: false,
      parameters: {
        depthTest: true,
      },
      onHover: (info) => {
        if (!setHoveredDistanceM) {
          return;
        }

        if (!info?.coordinate) {
          setHoveredDistanceM(null);
          return;
        }

        setHoveredDistanceM(nearestRouteDistance(samples, info.coordinate));
      },
    }),
  ];

  if (cursorPoint) {
    layers.push(
      new ScatterplotLayer({
        id: "route-hover-cursor",
        data: [cursorPoint],
        getPosition: (point) => [
          point.longitude,
          point.latitude,
          point.elevationM + 0.18,
        ],
        getFillColor: HOVER_COLOR,
        getLineColor: [255, 255, 255, 255],
        getRadius: 1.2,
        radiusUnits: "meters",
        stroked: true,
        lineWidthMinPixels: 2,
        pickable: false,
        parameters: {
          depthTest: false,
        },
      }),
    );
  }

  return layers;
}
