CREATE EXTENSION IF NOT EXISTS postgis;

ALTER TABLE accessibility_segments
ADD COLUMN IF NOT EXISTS geom geometry(LineStringZ, 4326);

CREATE INDEX IF NOT EXISTS accessibility_segments_geom_gix
ON accessibility_segments
USING GIST (geom);
