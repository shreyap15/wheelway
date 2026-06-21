const EARTH_RADIUS_M = 6371000;
const DEFAULT_SAMPLE_SPACING_M = 2.5;
const DEFAULT_RIBBON_WIDTH_M = 1.8;
const METERS_PER_DEGREE_LAT = 111320;

function toFiniteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function getLongitude(point) {
  return Array.isArray(point)
    ? toFiniteNumber(point[0])
    : toFiniteNumber(point?.longitude ?? point?.lng ?? point?.lon);
}

function getLatitude(point) {
  return Array.isArray(point)
    ? toFiniteNumber(point[1])
    : toFiniteNumber(point?.latitude ?? point?.lat);
}

function getElevation(point) {
  const value = Array.isArray(point)
    ? point[2]
    : point?.elevationM ?? point?.elevation_m ?? point?.elevation;

  return value === undefined || value === null ? null : toFiniteNumber(value, null);
}

function getSurfaceOffset(point) {
  return toFiniteNumber(
    point?.measuredSurfaceOffsetM ??
      point?.measured_surface_offset_m ??
      point?.surfaceOffsetM ??
      point?.surface_offset_m ??
      0,
  );
}

function getBumpHeight(point) {
  return toFiniteNumber(point?.bumpHeightM ?? point?.bump_height_m ?? 0);
}

function coordinatesEqual(a, b) {
  if (!a || !b) {
    return false;
  }

  return (
    Math.abs(a.longitude - b.longitude) < 1e-10 &&
    Math.abs(a.latitude - b.latitude) < 1e-10 &&
    (a.elevationM === null ||
      b.elevationM === null ||
      Math.abs(a.elevationM - b.elevationM) < 1e-4)
  );
}

export function haversineDistanceM(a, b) {
  const lat1 = (a.latitude * Math.PI) / 180;
  const lat2 = (b.latitude * Math.PI) / 180;
  const dLat = ((b.latitude - a.latitude) * Math.PI) / 180;
  const dLon = ((b.longitude - a.longitude) * Math.PI) / 180;

  const sinLat = Math.sin(dLat / 2);
  const sinLon = Math.sin(dLon / 2);
  const h =
    sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon;

  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function flattenOrderedRoute(routeSegments = []) {
  const route = [];
  let cumulativeDistanceM = 0;

  routeSegments.forEach((segment, segmentIndex) => {
    const coordinates = segment?.geometry?.coordinates ?? segment?.coordinates ?? [];

    coordinates.forEach((coordinate, coordinateIndex) => {
      const point = {
        longitude: getLongitude(coordinate),
        latitude: getLatitude(coordinate),
        elevationM: getElevation(coordinate),
        surfaceOffsetM: getSurfaceOffset(coordinate),
        bumpHeightM: getBumpHeight(coordinate),
        segment,
        segmentIndex,
        coordinateIndex,
        cumulativeDistanceM,
      };

      const previous = route.at(-1);
      if (coordinatesEqual(previous, point)) {
        return;
      }

      if (previous) {
        cumulativeDistanceM += haversineDistanceM(previous, point);
        point.cumulativeDistanceM = cumulativeDistanceM;
      }

      route.push(point);
    });
  });

  return route;
}

function interpolatePoint(a, b, ratio) {
  const elevationM =
    a.elevationM !== null && b.elevationM !== null
      ? a.elevationM + (b.elevationM - a.elevationM) * ratio
      : null;

  return {
    ...a,
    longitude: a.longitude + (b.longitude - a.longitude) * ratio,
    latitude: a.latitude + (b.latitude - a.latitude) * ratio,
    elevationM,
    surfaceOffsetM:
      a.surfaceOffsetM + (b.surfaceOffsetM - a.surfaceOffsetM) * ratio,
    bumpHeightM: a.bumpHeightM + (b.bumpHeightM - a.bumpHeightM) * ratio,
  };
}

export function densifyRoute(route, spacingM = DEFAULT_SAMPLE_SPACING_M) {
  if (route.length < 2) {
    return route.map((point) => ({ ...point }));
  }

  const samples = [{ ...route[0], cumulativeDistanceM: 0 }];
  let cumulativeDistanceM = 0;

  for (let index = 0; index < route.length - 1; index += 1) {
    const start = route[index];
    const end = route[index + 1];
    const segmentDistanceM = haversineDistanceM(start, end);
    const stepCount = Math.max(1, Math.ceil(segmentDistanceM / spacingM));

    for (let step = 1; step <= stepCount; step += 1) {
      const ratio = step / stepCount;
      const previousRatio = (step - 1) / stepCount;
      const previousPoint = interpolatePoint(start, end, previousRatio);
      const sample = interpolatePoint(start, end, ratio);

      cumulativeDistanceM += haversineDistanceM(previousPoint, sample);
      sample.cumulativeDistanceM = cumulativeDistanceM;
      samples.push(sample);
    }
  }

  return samples;
}

export function normalizeSurfaceSamples(surfaceSamples = []) {
  return surfaceSamples.map((sample) => ({
    longitude: getLongitude(sample),
    latitude: getLatitude(sample),
    elevationM: getElevation(sample),
    surfaceOffsetM: getSurfaceOffset(sample),
    confidence: toFiniteNumber(sample.confidence, 1),
  }));
}

export function nearestMeasuredSample(point, surfaceSamples, maxDistanceM = 2) {
  let nearest = null;
  let nearestDistanceM = Infinity;

  surfaceSamples.forEach((sample) => {
    const distanceM = haversineDistanceM(point, sample);
    if (distanceM < nearestDistanceM) {
      nearest = sample;
      nearestDistanceM = distanceM;
    }
  });

  return nearestDistanceM <= maxDistanceM ? nearest : null;
}

export function applySurfaceSamples(samples) {
  const normalizedBySegment = new WeakMap();

  return samples.map((sample) => {
    const segment = sample.segment;
    if (!segment) {
      return sample;
    }

    if (!normalizedBySegment.has(segment)) {
      normalizedBySegment.set(
        segment,
        normalizeSurfaceSamples(segment.surface_samples ?? segment.surfaceSamples),
      );
    }

    const measured = nearestMeasuredSample(sample, normalizedBySegment.get(segment));
    if (!measured) {
      return sample;
    }

    return {
      ...sample,
      elevationM: measured.elevationM ?? sample.elevationM,
      surfaceOffsetM: measured.surfaceOffsetM,
      measuredConfidence: measured.confidence,
    };
  });
}

export async function buildSampledRoute(routeSegments, terrainSampler) {
  const route = applySurfaceSamples(
    densifyRoute(flattenOrderedRoute(routeSegments), DEFAULT_SAMPLE_SPACING_M),
  );

  const sampled = [];

  for (const point of route) {
    let terrainElevationM = 0;

    if (point.elevationM === null && terrainSampler) {
      terrainElevationM = toFiniteNumber(await terrainSampler(point), 0);
    }

    const baseElevationM =
      point.elevationM === null ? terrainElevationM : point.elevationM;
    const measuredSurfaceOffsetM =
      point.measuredSurfaceOffsetM ?? point.measured_surface_offset_m;
    const surfaceOffsetM = toFiniteNumber(
      measuredSurfaceOffsetM ?? point.surfaceOffsetM,
      0,
    );
    const bumpHeightM = toFiniteNumber(point.bumpHeightM, 0);

    sampled.push({
      ...point,
      terrainElevationM,
      surfaceOffsetM,
      bumpHeightM,
      elevationM: baseElevationM + surfaceOffsetM + bumpHeightM,
    });
  }

  return sampled;
}

export function metersPerDegreeLon(latitude) {
  return METERS_PER_DEGREE_LAT * Math.cos((latitude * Math.PI) / 180);
}

function offsetCoordinate(point, rightMeters, upMeters) {
  const metersPerLon = Math.max(1, metersPerDegreeLon(point.latitude));

  return [
    point.longitude + rightMeters.east / metersPerLon,
    point.latitude + rightMeters.north / METERS_PER_DEGREE_LAT,
    point.elevationM + upMeters,
  ];
}

function directionForIndex(samples, index) {
  const previous = samples[Math.max(0, index - 1)];
  const next = samples[Math.min(samples.length - 1, index + 1)];
  const latitude = samples[index].latitude;
  const metersPerLon = metersPerDegreeLon(latitude);

  const east = (next.longitude - previous.longitude) * metersPerLon;
  const north = (next.latitude - previous.latitude) * METERS_PER_DEGREE_LAT;
  const length = Math.hypot(east, north) || 1;

  return {
    east: east / length,
    north: north / length,
  };
}

export function buildRibbonVertices(
  samples,
  widthM = DEFAULT_RIBBON_WIDTH_M,
) {
  return samples.map((point, index) => {
    const direction = directionForIndex(samples, index);
    const halfWidthM = widthM / 2;
    const perpendicular = {
      east: direction.north,
      north: -direction.east,
    };
    const crossSlopePct = toFiniteNumber(
      point.segment?.cross_slope ?? point.segment?.crossSlopePct,
      0,
    );
    const crossSlopeRiseM = (widthM * crossSlopePct) / 100;
    const leftRiseM = crossSlopeRiseM / 2;
    const rightRiseM = -crossSlopeRiseM / 2;

    const leftOffset = {
      east: perpendicular.east * halfWidthM,
      north: perpendicular.north * halfWidthM,
    };
    const rightOffset = {
      east: -perpendicular.east * halfWidthM,
      north: -perpendicular.north * halfWidthM,
    };

    return {
      ...point,
      left: offsetCoordinate(point, leftOffset, leftRiseM),
      right: offsetCoordinate(point, rightOffset, rightRiseM),
      center: [point.longitude, point.latitude, point.elevationM],
    };
  });
}

export function buildRibbonPolygons(samples, widthM = DEFAULT_RIBBON_WIDTH_M) {
  const vertices = buildRibbonVertices(samples, widthM);
  const top = [];
  const sides = [];

  for (let index = 0; index < vertices.length - 1; index += 1) {
    const current = vertices[index];
    const next = vertices[index + 1];
    const baseCurrentLeft = [...current.left];
    const baseCurrentRight = [...current.right];
    const baseNextLeft = [...next.left];
    const baseNextRight = [...next.right];

    baseCurrentLeft[2] = current.terrainElevationM;
    baseCurrentRight[2] = current.terrainElevationM;
    baseNextLeft[2] = next.terrainElevationM;
    baseNextRight[2] = next.terrainElevationM;

    top.push({
      polygon: [current.left, next.left, next.right, current.right],
      sample: current,
    });
    sides.push(
      {
        polygon: [current.left, baseCurrentLeft, baseNextLeft, next.left],
        sample: current,
      },
      {
        polygon: [current.right, next.right, baseNextRight, baseCurrentRight],
        sample: current,
      },
    );
  }

  return { top, sides, vertices };
}

function projectPointToEdge(point, start, end) {
  const latitude = (start.latitude + end.latitude) / 2;
  const metersPerLon = metersPerDegreeLon(latitude);
  const ax = start.longitude * metersPerLon;
  const ay = start.latitude * METERS_PER_DEGREE_LAT;
  const bx = end.longitude * metersPerLon;
  const by = end.latitude * METERS_PER_DEGREE_LAT;
  const px = point.longitude * metersPerLon;
  const py = point.latitude * METERS_PER_DEGREE_LAT;
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSq = dx * dx + dy * dy;
  const ratio = lengthSq === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSq));
  const projected = {
    longitude: (ax + dx * ratio) / metersPerLon,
    latitude: (ay + dy * ratio) / METERS_PER_DEGREE_LAT,
  };

  return {
    distanceM: haversineDistanceM(point, projected),
    ratio,
  };
}

export function nearestRouteDistance(samples, coordinate) {
  if (!coordinate || samples.length === 0) {
    return null;
  }

  const point = {
    longitude: getLongitude(coordinate),
    latitude: getLatitude(coordinate),
  };
  let nearest = null;

  for (let index = 0; index < samples.length - 1; index += 1) {
    const start = samples[index];
    const end = samples[index + 1];
    const projection = projectPointToEdge(point, start, end);
    const edgeDistanceM = Math.max(
      0,
      end.cumulativeDistanceM - start.cumulativeDistanceM,
    );
    const routeDistanceM =
      start.cumulativeDistanceM + edgeDistanceM * projection.ratio;

    if (!nearest || projection.distanceM < nearest.pickDistanceM) {
      nearest = {
        routeDistanceM,
        pickDistanceM: projection.distanceM,
      };
    }
  }

  return nearest?.routeDistanceM ?? null;
}

export function coordinateAtRouteDistance(samples, distanceM) {
  if (!samples.length || distanceM === null || distanceM === undefined) {
    return null;
  }

  if (distanceM <= 0) {
    return samples[0];
  }

  const last = samples.at(-1);
  if (distanceM >= last.cumulativeDistanceM) {
    return last;
  }

  for (let index = 0; index < samples.length - 1; index += 1) {
    const start = samples[index];
    const end = samples[index + 1];

    if (
      distanceM >= start.cumulativeDistanceM &&
      distanceM <= end.cumulativeDistanceM
    ) {
      const edgeDistanceM = end.cumulativeDistanceM - start.cumulativeDistanceM;
      const ratio = edgeDistanceM === 0 ? 0 : (distanceM - start.cumulativeDistanceM) / edgeDistanceM;
      return interpolatePoint(start, end, ratio);
    }
  }

  return last;
}

export function routeCenter(samples) {
  if (!samples.length) {
    return {
      longitude: -122.2585,
      latitude: 37.8719,
    };
  }

  const total = samples.reduce(
    (acc, point) => ({
      longitude: acc.longitude + point.longitude,
      latitude: acc.latitude + point.latitude,
    }),
    { longitude: 0, latitude: 0 },
  );

  return {
    longitude: total.longitude / samples.length,
    latitude: total.latitude / samples.length,
  };
}
