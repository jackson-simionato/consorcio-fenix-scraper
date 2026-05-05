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

## Onboard Advisory Readiness

The scraper database provides the read model needed for first-version Onboard Advisory flows, while the advisory app owns passenger-facing calculations and presentation.
Every public advisory read must continue to filter to current routes and current route versions before trusting the selected Route Direction:

- `routes.is_current = true`
- `route_versions.is_current = true`
- `route_versions.route_id = routes.id`
- `route_directions.route_version_id = route_versions.id`

Projected Route Position is supported by ordered Materialized Route Segments for the selected Route Direction.
The advisory app should load `route_segments` by `route_version_id` and `route_direction_id`, ordered by `route_segments.sequence`.
The scraper-owned fields that support projection are:

- `route_segments.geometry`, the directed segment geometry used for nearest-segment projection and segment proximity checks.
- `route_segments.sequence`, the stable segment order within the Route Direction.
- `route_segments.bearing_degrees`, the passenger-facing travel bearing for side-of-bus exposure calculations.
- `route_segments.distance_meters`, the segment length.
- `route_segments.cumulative_distance_meters`, the distance from the Route Direction start through the segment.
- `route_segments.source_segment_sequence`, `route_segments.source_fraction_start`, and `route_segments.source_fraction_end`, the lineage back to source KML geometry when debugging projection or segmentation.

Upcoming Exposure Window and Remaining Route Exposure are supported by the same ordered segment read.
The advisory app can derive an Upcoming Exposure Window from the Projected Route Position through the configured near-term distance or time horizon, and can derive Remaining Route Exposure from the Projected Route Position through the final segment of the selected Route Direction.
The scraper provides segment geometry, bearing, distance, and cumulative distance; the advisory app chooses the live windowing rule and aggregation.

Sun Position and Sun Exposure are advisory-app responsibilities.
The scraper does not precompute Sun Position, Sun Exposure, Sun-side Advisory output, segment timestamps, exposure windows, or passenger-facing side labels.
The advisory app computes Sun Position and Sun Exposure live from the selected Materialized Route Segments, passenger location, request datetime, and its own astronomy/exposure rules.

The default off-route threshold is 75 meters and belongs to the advisory app.
It is applied after segment proximity/projection against `route_segments.geometry`; if the Projected Route Position is farther than 75 meters from the selected Route Direction, the advisory app should withhold the Onboard Advisory.
The scraper only stores the segment geometries needed for that threshold check.

First-version advisories are Geometric Sun Exposure only.
They are not temperature, weather, shadow, seat-row, or fleet-specific cabin predictions.
Weather data, shade models, vehicle layout, curtain state, and cabin thermal behavior are outside the scraper contract.

Readiness checklist:

- Projected Route Position is covered by ordered `route_segments.geometry`, `route_segments.sequence`, `route_segments.distance_meters`, and `route_segments.cumulative_distance_meters`.
- Upcoming Exposure Window is covered by ordered segment reads after Projected Route Position; the advisory app owns the window horizon.
- Remaining Route Exposure is covered by ordered segment reads from Projected Route Position to the end of the selected Route Direction.
- Current route and current route version filtering is covered by `routes.is_current` and `route_versions.is_current`.
- Candidate Route Direction eligibility is covered by Materialized Route Segment existence for a current Route Direction.
- Candidate Direction Label fallback is covered by preferring `service_directions.departure_label` and falling back to `route_directions.name`.
- Sun Position and Sun Exposure live computation is intentionally outside this scraper.

## Future advisory-app work

The remaining gaps are advisory-app work, not scraper obligations:

- Choose the public Nearby Route Discovery radius and the exact Upcoming Exposure Window horizon.
- Implement Projected Route Position snapping and enforce the default 75 meters off-route threshold.
- Compute Sun Position and Geometric Sun Exposure live for the request datetime.
- Convert segment-level exposure into passenger-facing Onboard Advisory copy.
- Decide how to handle low GPS accuracy, stale browser location, and user-selected Candidate Route Direction mistakes.
- Add optional future models for weather, shadows, seat rows, fleet-specific cabin layout, and thermal comfort if the product scope expands beyond Geometric Sun Exposure only.
