# Candidate Route Direction Read Contract

This document is the read-only contract for the separate sun advisory app described in ADR-0003.
The advisory app consumes the scraper database read-only for Nearby Route Discovery, Candidate Route Direction selection, Projected Route Position, and Onboard Advisory flows.
It must not insert, update, delete, rebuild, or otherwise mutate scraper-owned route data.

## Eligibility

Public Nearby Route Discovery uses only current routes and current route versions:

- `routes.is_current = true`
- `route_versions.is_current = true`
- `route_versions.route_id = routes.id`

A Candidate Route Direction requires materialized segments: it is eligible only when it belongs to a current Route Version for a current Route and has one or more Materialized Route Segments.
Candidate Route Directions are found by Materialized Route Segment proximity, not stop proximity.
The `stops` table is not part of this first public discovery contract.

## Candidate Direction Label

Candidate Direction Label selection should prefer Service Direction labels when a Service Direction resolves to the candidate Route Direction.
Use `service_directions.departure_label` for labels such as "Saida Bairro" or "Saida TICEN" when available.
Fall back to the raw Route Direction name from `route_directions.name` only when no resolved Service Direction label exists.

Service Direction match confidence improves display context but does not determine Candidate Route Direction eligibility.
Materialized Route Segment existence determines eligibility.

## Query Shape

Inputs:

- `:longitude` and `:latitude` are the user's current location in SRID 4326.
- `:radius_meters` is the public Nearby Route Discovery radius.
- Optional `:limit` bounds returned Candidate Route Directions.

Pseudo-query:

```sql
WITH user_point AS (
  SELECT ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography AS geog
),
nearby_segments AS (
  SELECT
    rs.route_direction_id,
    MIN(ST_Distance(rs.geometry::geography, user_point.geog)) AS distance_meters
  FROM route_segments rs
  JOIN route_versions rv ON rv.id = rs.route_version_id
  JOIN routes r ON r.id = rv.route_id
  CROSS JOIN user_point
  WHERE r.is_current = true
    AND rv.is_current = true
    AND ST_DWithin(rs.geometry::geography, user_point.geog, :radius_meters)
  GROUP BY rs.route_direction_id
),
candidate_labels AS (
  SELECT
    rd.id AS route_direction_id,
    COALESCE(
      MIN(sd.departure_label) FILTER (WHERE sd.departure_label IS NOT NULL),
      rd.name
    ) AS candidate_direction_label
  FROM route_directions rd
  LEFT JOIN service_directions sd ON sd.route_direction_id = rd.id
  GROUP BY rd.id, rd.name
)
SELECT
  r.id AS route_id,
  r.code AS route_code,
  r.name AS route_name,
  rv.id AS route_version_id,
  rd.id AS route_direction_id,
  rd.sequence AS route_direction_sequence,
  cl.candidate_direction_label,
  ns.distance_meters
FROM nearby_segments ns
JOIN route_directions rd ON rd.id = ns.route_direction_id
JOIN route_versions rv ON rv.id = rd.route_version_id
JOIN routes r ON r.id = rv.route_id
JOIN candidate_labels cl ON cl.route_direction_id = rd.id
ORDER BY ns.distance_meters ASC, r.code ASC, rd.sequence ASC
LIMIT :limit;
```

The query discovers candidates from `route_segments`, so a Route Direction without Materialized Route Segments cannot appear.
The grouped segment scan returns one Candidate Route Direction per nearby Route Direction, with the closest Materialized Route Segment distance available for ranking.

## Returned Fields

The advisory app should treat these fields as stable identifiers and display inputs:

- `route_id`
- `route_code`
- `route_name`
- `route_version_id`
- `route_direction_id`
- `route_direction_sequence`
- `candidate_direction_label`
- `distance_meters`

The advisory app may use `route_direction_id` and `route_version_id` to load ordered Materialized Route Segments for Projected Route Position and Upcoming Exposure Window calculations.
Those follow-up reads must also filter to current routes and current route versions before trusting public Onboard Advisory output.
