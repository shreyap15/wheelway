import {
  PathLayer,
  PolygonLayer,
  ScatterplotLayer,
} from "@deck.gl/layers";
import { PathStyleExtension } from "@deck.gl/extensions";

import {
  accessibilityColor,
  accessibilitySideColor,
  buildGravityParticles,
  buildRouteRampMeshes,
  hazardDashPattern,
} from "./topographicalUtils";

/**
 * Precomputes all static geometry once.
 * The returned factory only rebuilds the lightweight animated particle layer.
 */
export function createTopographicalLayerFactory({
  routeSegments,
  meshOptions,
  particlesPerSegment = 7,
}) {
  const rampMeshes = buildRouteRampMeshes(
    routeSegments,
    meshOptions,
  );

  const topFaces = rampMeshes.flatMap((mesh) =>
    mesh.faces.filter((face) => face.face === "top"),
  );

  const sideFaces = rampMeshes.flatMap((mesh) =>
    mesh.faces.filter((face) => face.face !== "top"),
  );

  const warningCenterlines = rampMeshes
    .filter(
      (mesh) =>
        mesh.segment.accessibilityScore < 75,
    )
    .map((mesh) => ({
      ...mesh.segment,
      path: mesh.topCenterline.map(
        ([longitude, latitude, elevation]) => [
          longitude,
          latitude,
          elevation + 0.06,
        ],
      ),
    }));

  const staticLayers = [
    new PolygonLayer({
      id: "wheelway-ramp-side-faces",
      data: sideFaces,
      getPolygon: (face) => face.polygon,
      getFillColor: (face) =>
        accessibilitySideColor(
          face.accessibilityScore,
        ),
      getLineColor: [255, 255, 255, 75],
      getLineWidth: 0.6,
      lineWidthUnits: "pixels",
      filled: true,
      stroked: true,
      wireframe: false,
      extruded: false,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 70],
      material: {
        ambient: 0.42,
        diffuse: 0.72,
        shininess: 28,
        specularColor: [255, 255, 255],
      },
      parameters: {
        depthTest: true,
        depthMask: true,
      },
    }),

    new PolygonLayer({
      id: "wheelway-ramp-top-faces",
      data: topFaces,
      getPolygon: (face) => face.polygon,
      getFillColor: (face) =>
        accessibilityColor(
          face.accessibilityScore,
        ),
      getLineColor: [255, 255, 255, 125],
      getLineWidth: 1,
      lineWidthUnits: "pixels",
      filled: true,
      stroked: true,
      extruded: false,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 85],
      material: {
        ambient: 0.5,
        diffuse: 0.74,
        shininess: 45,
        specularColor: [255, 255, 255],
      },
      parameters: {
        depthTest: true,
        depthMask: true,
      },
    }),

    // Tactile warning / hazard crosshatch centerline.
    new PathLayer({
      id: "wheelway-ramp-warning-patterns",
      data: warningCenterlines,
      getPath: (segment) => segment.path,
      getColor: [255, 255, 255, 205],
      getWidth: 2.2,
      widthUnits: "pixels",
      widthMinPixels: 2,
      getDashArray: (segment) =>
        hazardDashPattern(segment),
      dashJustified: true,
      capRounded: false,
      jointRounded: false,
      pickable: false,
      extensions: [
        new PathStyleExtension({
          dash: true,
          highPrecisionDash: true,
        }),
      ],
      parameters: {
        depthTest: true,
      },
    }),
  ];

  return function buildLayers(animationTimeMs = 0) {
    const phaseSeconds = animationTimeMs / 1000;

    const gravityParticles =
      buildGravityParticles(
        rampMeshes,
        phaseSeconds,
        particlesPerSegment,
      );

    const particleLayer = new ScatterplotLayer({
      id: "wheelway-downhill-gravity-particles",
      data: gravityParticles,
      getPosition: (particle) => particle.position,
      getRadius: (particle) => particle.radiusPixels,
      radiusUnits: "pixels",
      radiusMinPixels: 2.5,
      radiusMaxPixels: 6,
      getFillColor: (particle) => particle.color,
      getLineColor: [255, 255, 255, 220],
      getLineWidth: 1,
      lineWidthUnits: "pixels",
      stroked: true,
      filled: true,
      billboard: true,
      pickable: false,
      parameters: {
        depthTest: true,
      },
      updateTriggers: {
        getPosition: animationTimeMs,
      },
    });

    return [...staticLayers, particleLayer];
  };
}

export function getRampTooltip(pickingInfo) {
  const object = pickingInfo?.object;
  const segment = object?.segment ?? object;

  if (!segment?.id) return null;

  const runningSlope =
    segment.runningSlopePct ?? 0;
  const crossSlope =
    segment.crossSlopePct ?? 0;

  const compliant =
    Math.abs(runningSlope) <= 5 &&
    Math.abs(crossSlope) <= 2 &&
    !segment.isStairs &&
    segment.type !== "stairs" &&
    segment.type !== "curb_no_ramp";

  return {
    html: `
      <div style="min-width:190px">
        <div style="font-weight:700;margin-bottom:6px">
          ${compliant
            ? "PROWAG Compliant"
            : "Exceeds Maximum Allowed Limit"}
        </div>
        <div>Running slope: ${runningSlope.toFixed(1)}%</div>
        <div>Cross slope: ${crossSlope.toFixed(1)}%</div>
        <div>Accessibility: ${Math.round(
          segment.accessibilityScore ?? 0,
        )}/100</div>
      </div>
    `,
    style: {
      backgroundColor: "rgba(2, 6, 23, 0.96)",
      color: "#f8fafc",
      fontSize: "12px",
      borderRadius: "12px",
      border: `1px solid ${
        compliant
          ? "rgba(45, 212, 191, 0.55)"
          : "rgba(244, 63, 94, 0.6)"
      }`,
      boxShadow:
        "0 14px 40px rgba(2, 6, 23, 0.4)",
      padding: "10px 12px",
      pointerEvents: "none",
    },
  };
}
