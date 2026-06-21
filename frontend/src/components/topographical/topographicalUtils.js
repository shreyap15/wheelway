/**
 * WheelWay topographical geometry utilities.
 *
 * Coordinate convention:
 *   [longitude, latitude, elevationMeters]
 *
 * The functions are pure and framework-independent so they can be tested
 * independently of React, Mapbox, and Deck.gl.
 */

export const PROWAG = Object.freeze({
  RUNNING_SLOPE_MAX_PCT: 5,
  CROSS_SLOPE_MAX_PCT: 2,
});

export const DEFAULT_MESH_OPTIONS = Object.freeze({
  ribbonWidthMeters: 3.2,
  ribbonThicknessMeters: 0.22,
  elevationMultiplier: 2.6,
  minimumLiftMeters: 0.35,
  samplesPerSegment: 8,
});

export const ACCESSIBILITY_COLORS = Object.freeze({
  safe: [20, 184, 166, 238],
  caution: [245, 158, 11, 242],
  danger: [225, 29, 72, 245],
  safeDark: [8, 92, 84, 235],
  cautionDark: [146, 64, 14, 235],
  dangerDark: [136, 19, 55, 240],
});

const EARTH_RADIUS_METERS = 6_371_000;
const METERS_PER_LATITUDE_DEGREE = 111_320;

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function lerp(start, end, amount) {
  return start + (end - start) * amount;
}

export function accessibilityBand(score = 100) {
  if (score >= 75) return "safe";
  if (score >= 40) return "caution";
  return "danger";
}

export function accessibilityColor(score, alpha) {
  const color = ACCESSIBILITY_COLORS[accessibilityBand(score)];
  return alpha == null ? color : [...color.slice(0, 3), alpha];
}

export function accessibilitySideColor(score, alpha) {
  const band = accessibilityBand(score);
  const color =
    band === "safe"
      ? ACCESSIBILITY_COLORS.safeDark
      : band === "caution"
        ? ACCESSIBILITY_COLORS.cautionDark
        : ACCESSIBILITY_COLORS.dangerDark;

  return alpha == null ? color : [...color.slice(0, 3), alpha];
}

export function isProwagCompliant(segment) {
  return (
    Math.abs(segment.runningSlopePct ?? 0) <=
      PROWAG.RUNNING_SLOPE_MAX_PCT &&
    Math.abs(segment.crossSlopePct ?? 0) <=
      PROWAG.CROSS_SLOPE_MAX_PCT &&
    !segment.isStairs &&
    segment.type !== "stairs" &&
    segment.type !== "curb_no_ramp"
  );
}

export function complianceLabel(segment) {
  return isProwagCompliant(segment)
    ? "PROWAG Compliant"
    : "Exceeds Maximum Allowed Limit";
}

export function haversineMeters(a, b) {
  const toRadians = (degrees) => (degrees * Math.PI) / 180;
  const [lng1, lat1] = a;
  const [lng2, lat2] = b;

  const deltaLatitude = toRadians(lat2 - lat1);
  const deltaLongitude = toRadians(lng2 - lng1);
  const latitude1 = toRadians(lat1);
  const latitude2 = toRadians(lat2);

  const h =
    Math.sin(deltaLatitude / 2) ** 2 +
    Math.cos(latitude1) *
      Math.cos(latitude2) *
      Math.sin(deltaLongitude / 2) ** 2;

  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.sqrt(h));
}

export function segmentLengthMeters(segment) {
  const points = segment.coordinates ?? [];

  return points.slice(1).reduce(
    (distance, point, index) =>
      distance + haversineMeters(points[index], point),
    0,
  );
}

export function buildElevationProfile(routeSegments) {
  let cumulativeDistanceMeters = 0;
  const profile = [];

  routeSegments.forEach((segment, index) => {
    const firstPoint = segment.coordinates?.[0];
    const finalPoint = segment.coordinates?.at(-1);

    if (!firstPoint || !finalPoint) return;

    if (index === 0) {
      profile.push({
        distanceMeters: 0,
        elevationMeters: firstPoint[2] ?? segment.startElevationM ?? 0,
        runningSlopePct: segment.runningSlopePct ?? 0,
        crossSlopePct: segment.crossSlopePct ?? 0,
        exceedsRunningSlope:
          Math.abs(segment.runningSlopePct ?? 0) >
          PROWAG.RUNNING_SLOPE_MAX_PCT,
        exceedsCrossSlope:
          Math.abs(segment.crossSlopePct ?? 0) >
          PROWAG.CROSS_SLOPE_MAX_PCT,
        segmentId: segment.id,
      });
    }

    cumulativeDistanceMeters += segmentLengthMeters(segment);

    profile.push({
      distanceMeters: Math.round(cumulativeDistanceMeters),
      elevationMeters: finalPoint[2] ?? segment.endElevationM ?? 0,
      runningSlopePct: segment.runningSlopePct ?? 0,
      crossSlopePct: segment.crossSlopePct ?? 0,
      exceedsRunningSlope:
        Math.abs(segment.runningSlopePct ?? 0) >
        PROWAG.RUNNING_SLOPE_MAX_PCT,
      exceedsCrossSlope:
        Math.abs(segment.crossSlopePct ?? 0) >
        PROWAG.CROSS_SLOPE_MAX_PCT,
      segmentId: segment.id,
    });
  });

  return profile;
}

export function summarizeTopographicalRoute(routeSegments) {
  if (!routeSegments.length) {
    return {
      totalDistanceMeters: 0,
      maximumInclinePct: 0,
      averageAccessibilityScore: 0,
      hasObstacle: false,
    };
  }

  const lengths = routeSegments.map(segmentLengthMeters);
  const totalDistanceMeters = lengths.reduce(
    (sum, length) => sum + length,
    0,
  );

  const weightedScore =
    routeSegments.reduce(
      (sum, segment, index) =>
        sum +
        (segment.accessibilityScore ?? 0) * lengths[index],
      0,
    ) / Math.max(totalDistanceMeters, 1);

  const maximumInclinePct = Math.max(
    ...routeSegments.map((segment) =>
      Math.abs(segment.runningSlopePct ?? 0),
    ),
  );

  const hasObstacle = routeSegments.some(
    (segment) =>
      !isProwagCompliant(segment) ||
      (segment.accessibilityScore ?? 100) < 40,
  );

  return {
    totalDistanceMeters,
    maximumInclinePct,
    averageAccessibilityScore: weightedScore,
    hasObstacle,
  };
}

export function metersPerLongitudeDegree(latitude) {
  return (
    METERS_PER_LATITUDE_DEGREE *
    Math.cos((latitude * Math.PI) / 180)
  );
}

export function offsetCoordinate(
  coordinate,
  eastMeters,
  northMeters,
  elevationDeltaMeters = 0,
) {
  const [longitude, latitude, elevation = 0] = coordinate;

  return [
    longitude +
      eastMeters / metersPerLongitudeDegree(latitude),
    latitude +
      northMeters / METERS_PER_LATITUDE_DEGREE,
    elevation + elevationDeltaMeters,
  ];
}

export function interpolateCoordinate(start, end, amount) {
  return [
    lerp(start[0], end[0], amount),
    lerp(start[1], end[1], amount),
    lerp(start[2] ?? 0, end[2] ?? 0, amount),
  ];
}

function localDirectionMeters(start, end) {
  const midpointLatitude = (start[1] + end[1]) / 2;

  const eastMeters =
    (end[0] - start[0]) *
    metersPerLongitudeDegree(midpointLatitude);

  const northMeters =
    (end[1] - start[1]) *
    METERS_PER_LATITUDE_DEGREE;

  const lengthMeters = Math.hypot(eastMeters, northMeters) || 1;

  return {
    eastUnit: eastMeters / lengthMeters,
    northUnit: northMeters / lengthMeters,
    perpendicularEastUnit: -northMeters / lengthMeters,
    perpendicularNorthUnit: eastMeters / lengthMeters,
    lengthMeters,
  };
}

/**
 * Resolves terrain/base elevations and applies an adjustable visual multiplier.
 *
 * When explicit Z coordinates are unavailable, the running slope determines
 * end elevation using rise = run * slope. This keeps the standalone mock and
 * live 2D route responses visually functional.
 */
export function resolveSegmentElevations(
  segment,
  {
    elevationMultiplier = DEFAULT_MESH_OPTIONS.elevationMultiplier,
    minimumLiftMeters = DEFAULT_MESH_OPTIONS.minimumLiftMeters,
  } = {},
) {
  const start = segment.coordinates[0];
  const end = segment.coordinates.at(-1);
  const lengthMeters = segmentLengthMeters(segment);

  const rawStartElevation = Number.isFinite(start[2])
    ? start[2]
    : segment.startElevationM ?? 0;

  const rawEndElevation = Number.isFinite(end[2])
    ? end[2]
    : Number.isFinite(segment.endElevationM)
      ? segment.endElevationM
      : rawStartElevation +
        lengthMeters *
          ((segment.runningSlopePct ?? 0) / 100);

  const rawDelta = rawEndElevation - rawStartElevation;
  const visualDelta = rawDelta * elevationMultiplier;

  return {
    baseStartElevation: rawStartElevation,
    baseEndElevation: rawEndElevation,
    visualStartElevation:
      rawStartElevation + minimumLiftMeters,
    visualEndElevation:
      rawStartElevation +
      visualDelta +
      minimumLiftMeters,
    rawDelta,
    visualDelta,
    lengthMeters,
  };
}

/**
 * Builds a thick skateboard-ramp style mesh from one route segment.
 *
 * Running slope controls longitudinal pitch.
 * Cross slope offsets the left and right corners in opposite Z directions,
 * producing a visible twist instead of a flat strip.
 */
export function buildRampMesh(
  segment,
  options = {},
) {
  const {
    ribbonWidthMeters,
    ribbonThicknessMeters,
    elevationMultiplier,
    minimumLiftMeters,
  } = {
    ...DEFAULT_MESH_OPTIONS,
    ...options,
  };

  const startInput = segment.coordinates[0];
  const endInput = segment.coordinates.at(-1);
  const direction = localDirectionMeters(startInput, endInput);

  const elevations = resolveSegmentElevations(segment, {
    elevationMultiplier,
    minimumLiftMeters,
  });

  const halfWidth = ribbonWidthMeters / 2;
  const crossSlopeRise =
    ribbonWidthMeters *
    ((segment.crossSlopePct ?? 0) / 100) *
    elevationMultiplier;

  const leftCrossOffset = crossSlopeRise / 2;
  const rightCrossOffset = -crossSlopeRise / 2;

  const startCenter = [
    startInput[0],
    startInput[1],
    elevations.visualStartElevation,
  ];

  const endCenter = [
    endInput[0],
    endInput[1],
    elevations.visualEndElevation,
  ];

  const leftEast =
    direction.perpendicularEastUnit * halfWidth;
  const leftNorth =
    direction.perpendicularNorthUnit * halfWidth;

  const topStartLeft = offsetCoordinate(
    startCenter,
    leftEast,
    leftNorth,
    leftCrossOffset,
  );

  const topStartRight = offsetCoordinate(
    startCenter,
    -leftEast,
    -leftNorth,
    rightCrossOffset,
  );

  const topEndLeft = offsetCoordinate(
    endCenter,
    leftEast,
    leftNorth,
    leftCrossOffset,
  );

  const topEndRight = offsetCoordinate(
    endCenter,
    -leftEast,
    -leftNorth,
    rightCrossOffset,
  );

  const bottomStartLeft = [
    topStartLeft[0],
    topStartLeft[1],
    topStartLeft[2] - ribbonThicknessMeters,
  ];

  const bottomStartRight = [
    topStartRight[0],
    topStartRight[1],
    topStartRight[2] - ribbonThicknessMeters,
  ];

  const bottomEndLeft = [
    topEndLeft[0],
    topEndLeft[1],
    topEndLeft[2] - ribbonThicknessMeters,
  ];

  const bottomEndRight = [
    topEndRight[0],
    topEndRight[1],
    topEndRight[2] - ribbonThicknessMeters,
  ];

  const common = {
    segment,
    accessibilityScore: segment.accessibilityScore,
    runningSlopePct: segment.runningSlopePct ?? 0,
    crossSlopePct: segment.crossSlopePct ?? 0,
    compliance: complianceLabel(segment),
  };

  return {
    segment,
    topCenterline: [startCenter, endCenter],
    downhillCenterline:
      elevations.visualEndElevation >
      elevations.visualStartElevation
        ? [endCenter, startCenter]
        : [startCenter, endCenter],
    faces: [
      {
        ...common,
        face: "top",
        polygon: [
          topStartLeft,
          topEndLeft,
          topEndRight,
          topStartRight,
          topStartLeft,
        ],
      },
      {
        ...common,
        face: "left",
        polygon: [
          topStartLeft,
          topEndLeft,
          bottomEndLeft,
          bottomStartLeft,
          topStartLeft,
        ],
      },
      {
        ...common,
        face: "right",
        polygon: [
          topStartRight,
          topEndRight,
          bottomEndRight,
          bottomStartRight,
          topStartRight,
        ],
      },
      {
        ...common,
        face: "start-cap",
        polygon: [
          topStartLeft,
          topStartRight,
          bottomStartRight,
          bottomStartLeft,
          topStartLeft,
        ],
      },
      {
        ...common,
        face: "end-cap",
        polygon: [
          topEndLeft,
          topEndRight,
          bottomEndRight,
          bottomEndLeft,
          topEndLeft,
        ],
      },
    ],
  };
}

export function buildRouteRampMeshes(
  segments,
  options = {},
) {
  return segments.map((segment) =>
    buildRampMesh(segment, options),
  );
}

export function hazardDashPattern(segment) {
  const band = accessibilityBand(
    segment.accessibilityScore,
  );

  if (band === "danger") return [2, 1];
  if (band === "caution") return [5, 2];
  return [1, 0];
}

export function slopeSeverity(segment) {
  const runningRatio =
    Math.abs(segment.runningSlopePct ?? 0) /
    PROWAG.RUNNING_SLOPE_MAX_PCT;

  const crossRatio =
    Math.abs(segment.crossSlopePct ?? 0) /
    PROWAG.CROSS_SLOPE_MAX_PCT;

  return Math.max(runningRatio, crossRatio);
}

export function particleSpeed(segment) {
  const severity = slopeSeverity(segment);
  return clamp(0.06 + severity * 0.055, 0.08, 0.42);
}

/**
 * Generates particle positions without React state.
 * phase is expressed in seconds.
 */
export function buildGravityParticles(
  rampMeshes,
  phaseSeconds,
  particlesPerSegment = 7,
) {
  const particles = [];

  for (const mesh of rampMeshes) {
    const segment = mesh.segment;
    const band = accessibilityBand(
      segment.accessibilityScore,
    );

    if (band === "safe") continue;

    const speed = particleSpeed(segment);
    const [downhillStart, downhillEnd] =
      mesh.downhillCenterline;

    for (
      let index = 0;
      index < particlesPerSegment;
      index += 1
    ) {
      const offset = index / particlesPerSegment;
      const progress =
        (offset + phaseSeconds * speed) % 1;

      particles.push({
        segment,
        position: interpolateCoordinate(
          downhillStart,
          downhillEnd,
          progress,
        ),
        radiusPixels:
          band === "danger" ? 4.3 : 3.5,
        color: accessibilityColor(
          segment.accessibilityScore,
          245,
        ),
      });
    }
  }

  return particles;
}

/**
 * Standalone 4x4 Berkeley-style fixture.
 * Consumers can replace this with route data from the existing backend.
 */
export function createMockGrid4x4() {
  const origin = [-122.2688, 37.8694];
  const longitudeStep = 0.001;
  const latitudeStep = 0.00078;
  const rowElevation = [48, 53, 61, 72];

  const nodes = Array.from(
    { length: 4 },
    (_, row) =>
      Array.from({ length: 4 }, (_, column) => ({
        id: `n-${row}-${column}`,
        coordinates: [
          origin[0] + column * longitudeStep,
          origin[1] + row * latitudeStep,
          rowElevation[row] +
            column * 0.65 +
            row * column * 0.18,
        ],
      })),
  ).flat();

  const nodeById = Object.fromEntries(
    nodes.map((node) => [node.id, node]),
  );

  const makeSegment = ({
    id,
    from,
    to,
    accessibilityScore,
    runningSlopePct,
    crossSlopePct,
    surface = "concrete",
    type = "sidewalk",
    isStairs = false,
  }) => ({
    id,
    from,
    to,
    coordinates: [
      nodeById[from].coordinates,
      nodeById[to].coordinates,
    ],
    accessibilityScore,
    runningSlopePct,
    crossSlopePct,
    surface,
    type,
    isStairs,
  });

  const routeSegments = [
    makeSegment({
      id: "route-0",
      from: "n-0-0",
      to: "n-0-1",
      accessibilityScore: 91,
      runningSlopePct: 1.8,
      crossSlopePct: 1.1,
    }),
    makeSegment({
      id: "route-1",
      from: "n-0-1",
      to: "n-1-1",
      accessibilityScore: 67,
      runningSlopePct: 6.4,
      crossSlopePct: 1.9,
      surface: "brick",
    }),
    makeSegment({
      id: "route-2",
      from: "n-1-1",
      to: "n-1-2",
      accessibilityScore: 48,
      runningSlopePct: 7.8,
      crossSlopePct: 2.8,
      surface: "cracked_asphalt",
    }),
    makeSegment({
      id: "route-3",
      from: "n-1-2",
      to: "n-2-2",
      accessibilityScore: 24,
      runningSlopePct: 11.6,
      crossSlopePct: 3.7,
      surface: "broken_concrete",
    }),
    makeSegment({
      id: "route-4",
      from: "n-2-2",
      to: "n-2-3",
      accessibilityScore: 8,
      runningSlopePct: 14.2,
      crossSlopePct: 4.1,
      type: "curb_no_ramp",
    }),
  ];

  return {
    nodes,
    routeSegments,
    center: [-122.26725, 37.8707],
  };
}

export const MOCK_GRID_4X4 = createMockGrid4x4();
