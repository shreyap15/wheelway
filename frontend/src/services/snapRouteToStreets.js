import { haversineDistanceM } from "../components/topographical/topographicalUtils";

const MAPBOX_BASE_URL = "https://api.mapbox.com";
const DEFAULT_PROFILE = "walking";
const DEFAULT_MODE = "directions";
const MAX_DIRECTIONS_WAYPOINTS = 25;
const MAX_MATCHING_COORDINATES = 100;

const PROFILE_ALIASES = {
  pedestrian: "walking",
  sidewalk: "walking",
  walk: "walking",
  walking: "walking",
  vehicle: "driving",
  car: "driving",
  driving: "driving",
  bicycle: "cycling",
  bike: "cycling",
  cycling: "cycling",
};

function toFiniteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function coordinateToPoint(coordinate) {
  if (Array.isArray(coordinate)) {
    return {
      longitude: toFiniteNumber(coordinate[0]),
      latitude: toFiniteNumber(coordinate[1]),
      elevationM:
        coordinate[2] === undefined || coordinate[2] === null
          ? null
          : toFiniteNumber(coordinate[2], null),
    };
  }

  return {
    longitude: toFiniteNumber(
      coordinate?.longitude ?? coordinate?.lng ?? coordinate?.lon,
    ),
    latitude: toFiniteNumber(coordinate?.latitude ?? coordinate?.lat),
    elevationM:
      coordinate?.elevationM ??
      coordinate?.elevation_m ??
      coordinate?.elevation ??
      null,
  };
}

function pointToLngLat(point) {
  return [point.longitude, point.latitude];
}

function pointToLngLatZ(point) {
  return [
    point.longitude,
    point.latitude,
    point.elevationM === null ? 0 : point.elevationM,
  ];
}

function getSegmentCoordinates(segment) {
  const coordinates = segment?.geometry?.coordinates ?? segment?.coordinates ?? [];
  return coordinates.map(coordinateToPoint);
}

function normalizeProfile(profile) {
  const key = String(profile ?? DEFAULT_PROFILE).toLowerCase();
  return PROFILE_ALIASES[key] ?? DEFAULT_PROFILE;
}

function mapboxProfile(profile) {
  return `mapbox/${normalizeProfile(profile)}`;
}

function coordinatesParam(points) {
  return points
    .map((point) => `${point.longitude.toFixed(7)},${point.latitude.toFixed(7)}`)
    .join(";");
}

function cumulativeDistances(points) {
  const distances = [0];

  for (let index = 1; index < points.length; index += 1) {
    distances[index] =
      distances[index - 1] + haversineDistanceM(points[index - 1], points[index]);
  }

  return distances;
}

function interpolateElevationAtDistance(points, distances, distanceM) {
  if (!points.length) {
    return 0;
  }

  const firstElevation = points[0].elevationM;
  if (points.length === 1 || distanceM <= 0) {
    return firstElevation ?? 0;
  }

  const lastIndex = points.length - 1;
  if (distanceM >= distances[lastIndex]) {
    return points[lastIndex].elevationM ?? firstElevation ?? 0;
  }

  for (let index = 1; index < distances.length; index += 1) {
    if (distanceM > distances[index]) {
      continue;
    }

    const start = points[index - 1];
    const end = points[index];
    const startElevation = start.elevationM ?? end.elevationM ?? 0;
    const endElevation = end.elevationM ?? start.elevationM ?? startElevation;
    const spanM = distances[index] - distances[index - 1];
    const ratio = spanM === 0 ? 0 : (distanceM - distances[index - 1]) / spanM;

    return startElevation + (endElevation - startElevation) * ratio;
  }

  return points[lastIndex].elevationM ?? firstElevation ?? 0;
}

function addInterpolatedElevation(snappedLngLat, sourcePoints) {
  const snappedPoints = snappedLngLat.map(coordinateToPoint);
  const snappedDistances = cumulativeDistances(snappedPoints);
  const sourceDistances = cumulativeDistances(sourcePoints);
  const sourceTotalM = sourceDistances.at(-1) ?? 0;
  const snappedTotalM = snappedDistances.at(-1) ?? 0;

  return snappedPoints.map((point, index) => {
    const normalizedDistanceM =
      snappedTotalM === 0
        ? 0
        : (snappedDistances[index] / snappedTotalM) * sourceTotalM;

    return [
      point.longitude,
      point.latitude,
      interpolateElevationAtDistance(
        sourcePoints,
        sourceDistances,
        normalizedDistanceM,
      ),
    ];
  });
}

function shouldDropDuplicateJoin(previousCoordinate, coordinate) {
  if (!previousCoordinate) {
    return false;
  }

  return (
    Math.abs(previousCoordinate[0] - coordinate[0]) < 1e-10 &&
    Math.abs(previousCoordinate[1] - coordinate[1]) < 1e-10
  );
}

function normalizeRouteShape(routeOrSegments) {
  if (Array.isArray(routeOrSegments)) {
    return {
      route: {
        found: true,
        segments: routeOrSegments,
      },
      unwrapSegments: true,
    };
  }

  return {
    route: {
      ...routeOrSegments,
      segments: routeOrSegments?.segments ?? [],
    },
    unwrapSegments: false,
  };
}

async function fetchMapboxGeometry(sourcePoints, options) {
  const {
    accessToken,
    mode = DEFAULT_MODE,
    profile = DEFAULT_PROFILE,
    signal,
    useIntermediateWaypoints = false,
  } = options;
  const maxCoordinates =
    mode === "matching" ? MAX_MATCHING_COORDINATES : MAX_DIRECTIONS_WAYPOINTS;
  const requestSourcePoints =
    mode === "matching" || useIntermediateWaypoints
      ? sourcePoints
      : [sourcePoints[0], sourcePoints.at(-1)];
  const points = requestSourcePoints.slice(0, maxCoordinates);
  const endpoint = mode === "matching" ? "matching" : "directions";
  const url = new URL(
    `${MAPBOX_BASE_URL}/${endpoint}/v5/${mapboxProfile(profile)}/${coordinatesParam(points)}`,
  );

  url.searchParams.set("access_token", accessToken);
  url.searchParams.set("geometries", "geojson");
  url.searchParams.set("overview", "full");
  url.searchParams.set("steps", "false");

  if (mode === "directions") {
    url.searchParams.set("alternatives", "false");
  }

  const response = await fetch(url, { signal });
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(
      payload?.message ?? `Mapbox ${endpoint} request failed (${response.status})`,
    );
  }

  const candidate =
    mode === "matching" ? payload?.matchings?.[0] : payload?.routes?.[0];
  const coordinates = candidate?.geometry?.coordinates;

  if (!Array.isArray(coordinates) || coordinates.length < 2) {
    throw new Error(`Mapbox ${endpoint} response did not include a LineString`);
  }

  return {
    coordinates,
    distanceM: candidate.distance,
    durationS: candidate.duration,
  };
}

function fallbackDenseCoordinates(sourcePoints) {
  return sourcePoints.map(pointToLngLat);
}

function normalizeSegmentForMesh(segment, coordinatesWithElevation, metadata) {
  const lengthM = coordinatesWithElevation
    .map(coordinateToPoint)
    .reduce((sum, point, index, points) => {
      if (index === 0) {
        return 0;
      }

      return sum + haversineDistanceM(points[index - 1], point);
    }, 0);

  return {
    ...segment,
    id: segment.id ?? segment.segment_id,
    coordinates: coordinatesWithElevation,
    accessibilityScore:
      segment.accessibilityScore ?? segment.accessibility_score ?? 100,
    runningSlopePct: segment.runningSlopePct ?? segment.slope ?? 0,
    crossSlopePct: segment.crossSlopePct ?? segment.cross_slope ?? 0,
    type:
      segment.type ??
      (segment.has_obstruction ? "curb_no_ramp" : "sidewalk"),
    surface: segment.surface ?? "unknown",
    length_m: Number.isFinite(lengthM) && lengthM > 0 ? lengthM : segment.length_m,
    geometry: {
      type: "LineString",
      coordinates: coordinatesWithElevation,
    },
    snapping: metadata,
  };
}

async function snapSegmentToStreets(segment, options) {
  const sourcePoints = getSegmentCoordinates(segment);

  if (sourcePoints.length < 2) {
    return normalizeSegmentForMesh(segment, [], {
      snapped: false,
      reason: "segment has fewer than two coordinates",
    });
  }

  if (segment.snapping?.snapped && !options.force) {
    const coordinatesWithElevation = sourcePoints.map(pointToLngLatZ);

    return normalizeSegmentForMesh(segment, coordinatesWithElevation, {
      ...segment.snapping,
      preserved: true,
    });
  }

  try {
    const result = options.accessToken
      ? await fetchMapboxGeometry(sourcePoints, options)
      : {
          coordinates: fallbackDenseCoordinates(sourcePoints),
          distanceM: null,
          durationS: null,
        };
    const coordinatesWithElevation = addInterpolatedElevation(
      result.coordinates,
      sourcePoints,
    );

    return normalizeSegmentForMesh(segment, coordinatesWithElevation, {
      snapped: Boolean(options.accessToken),
      mode: options.mode ?? DEFAULT_MODE,
      profile: normalizeProfile(options.profile),
      sourceCoordinateCount: sourcePoints.length,
      snappedCoordinateCount: coordinatesWithElevation.length,
      distanceM: result.distanceM,
      durationS: result.durationS,
    });
  } catch (error) {
    if (options.strict) {
      throw error;
    }

    const fallbackCoordinates = addInterpolatedElevation(
      fallbackDenseCoordinates(sourcePoints),
      sourcePoints,
    );

    return normalizeSegmentForMesh(segment, fallbackCoordinates, {
      snapped: false,
      mode: options.mode ?? DEFAULT_MODE,
      profile: normalizeProfile(options.profile),
      sourceCoordinateCount: sourcePoints.length,
      snappedCoordinateCount: fallbackCoordinates.length,
      error: error.message,
    });
  }
}

function recomputeCumulativeSegments(segments) {
  let cumulativeDistanceM = 0;

  return segments.map((segment) => {
    cumulativeDistanceM += toFiniteNumber(segment.length_m, 0);

    return {
      ...segment,
      cumulative_distance_m: cumulativeDistanceM,
    };
  });
}

export async function snapRouteToStreets(routeOrSegments, options = {}) {
  const { route, unwrapSegments } = normalizeRouteShape(routeOrSegments);
  const snappedSegments = [];

  for (const segment of route.segments) {
    const snappedSegment = await snapSegmentToStreets(segment, options);
    const previous = snappedSegments.at(-1);
    const previousLastCoordinate =
      previous?.geometry?.coordinates?.at(-1) ?? previous?.coordinates?.at(-1);
    const firstCoordinate = snappedSegment.geometry.coordinates[0];

    if (
      previous &&
      shouldDropDuplicateJoin(previousLastCoordinate, firstCoordinate)
    ) {
      snappedSegment.geometry.coordinates = snappedSegment.geometry.coordinates.slice(1);
      snappedSegment.coordinates = snappedSegment.coordinates.slice(1);
    }

    snappedSegments.push(snappedSegment);
  }

  const segmentsWithDistance = recomputeCumulativeSegments(snappedSegments);
  const totalDistanceM = segmentsWithDistance.at(-1)?.cumulative_distance_m ?? 0;
  const snappedRoute = {
    ...route,
    segments: segmentsWithDistance,
    total_distance_m: totalDistanceM,
    snapping: {
      snapped: segmentsWithDistance.some((segment) => segment.snapping?.snapped),
      mode: options.mode ?? DEFAULT_MODE,
      profile: normalizeProfile(options.profile),
    },
  };

  return unwrapSegments ? snappedRoute.segments : snappedRoute;
}
