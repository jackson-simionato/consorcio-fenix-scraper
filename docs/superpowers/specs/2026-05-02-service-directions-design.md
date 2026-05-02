# Service Directions Design

## Goal

Schedules on Consorcio Fenix route pages are grouped by departure labels, while map pages expose directed KML geometries named with labels such as `IDA` and `VOLTA`. The scraper must preserve both concepts and store an inferred relationship between them so downstream applications can resolve a scheduled departure to the direction the bus is traveling.

The future sun and heat exposure application depends on directed travel geometry. A schedule entry must be able to resolve to a LineString whose coordinate order represents bus movement from the departure side toward the destination side. The scraper should store low-confidence inferred links too, as long as the inference method and confidence are explicit.

## Source Observations

For `https://www.consorciofenix.com.br/horarios/bairro-de-fatima,V-844`, the route page groups schedules under:

- `Saída Bairro de Fátima`
- `Saída TICEN - Plataforma B - Box 6`

The map page embeds KML with two directed `Placemark` geometries:

- `VOLTA`
- `IDA`

The source HTML does not provide a shared identifier between schedule groups and KML placemarks. The relationship must therefore be inferred from schedule group order, KML naming, endpoint evidence, and route-specific labels.

## Data Model

Keep `route_directions` as the table for KML geometries. A `route_direction` means: "the bus travels along this geometry from the first coordinate to the last coordinate." Its geometry order is semantically important and must not be normalized or reversed without also updating the direction metadata.

Add `service_directions` as a route-version child table representing the departure groups visible on schedule pages.

Columns:

- `id`
- `route_version_id`
- `sequence`
- `departure_label`
- `normalized_name`
- `direction_kind`
- `route_direction_id`
- `match_confidence`
- `match_method`
- `match_notes`

`route_direction_id` is nullable and references `route_directions.id`. It may be populated even for low-confidence matches when the scraper has a plausible inference.

`match_confidence` uses explicit values:

- `high`
- `medium`
- `low`
- `none`

`match_method` records how the link was chosen. Initial values:

- `label_endpoint`
- `label_order_ida_volta`
- `sequence_ida_volta`
- `unmatched`

`schedule_entries` gets a required `service_direction_id` FK. Keep the existing `departure_label` column as denormalized compatibility and debugging data for the first migration.

## Parsing

The route page parser should expose schedule groups explicitly instead of only returning flattened schedule entries. The domain should include a `ServiceDirection` model with:

- `sequence`
- `departure_label`
- `schedules`

Each schedule entry belongs to exactly one service direction. The parser continues to support table-based fallback pages, but the preferred live-page path is to read `.my-subtab-content` blocks, extract the heading as `departure_label`, and attach the contained `data-semana` and `data-horario` entries to that group.

The KML parser keeps producing `RouteDirection` rows with source names and coordinate order unchanged.

## Inference

After parsing the route page and KML, the scraper attempts to link each service direction to one route direction.

Rules:

1. High confidence: the departure label clearly matches a route geometry endpoint or a known terminal marker.
2. Medium confidence: KML name contains `ida` or `volta`, and schedule label/order strongly matches the Consorcio Fenix convention observed on sampled routes.
3. Low confidence: only source order and `ida`/`volta` naming convention suggest a link.
4. None: no usable inference exists.

Low-confidence links are persisted with `match_confidence = "low"` and a concrete `match_method`. Unmatched rows are persisted with `route_direction_id = null`, `match_confidence = "none"`, and `match_method = "unmatched"`.

The initial implementation may use conservative sequence plus `ida`/`volta` inference:

- A schedule group whose label indicates departure from the non-terminal side usually maps to `IDA`.
- A schedule group whose label indicates departure from TICEN/TITRI/terminal side usually maps to `VOLTA`.
- If only order is available, use a low-confidence match rather than hiding the inferred relationship.

These rules must be isolated in a small inference function so better endpoint matching can replace or augment them later.

## Persistence Flow

For a new route version:

1. Insert KML `route_directions`.
2. Infer service-direction-to-route-direction links.
3. Insert `service_directions`.
4. Insert `schedule_entries` with `service_direction_id`.
5. Keep `schedule_entries.departure_label` populated from the parent service direction.

When an unchanged route version is reused, do not duplicate route directions, service directions, or schedule entries.

## Downstream Contract

Consumers that need directed travel geometry should join:

`schedule_entries -> service_directions -> route_directions`

For sun and heat exposure, downstream logic should use the route direction geometry only when `route_direction_id` is present. It may decide its own confidence threshold. A strict first version should use `high` and `medium`; low-confidence rows should be audit-friendly because the scraper preserves the inference method and notes.

## Testing

Add parser and persistence coverage for:

- Live-style route HTML with two schedule groups creates two service directions.
- Schedule entries reference the correct service direction.
- KML `IDA` and `VOLTA` geometries preserve coordinate order.
- V-844-like data stores inferred links with confidence and method.
- Ambiguous data still stores service directions and schedule entries, with null or low-confidence geometry links.
- Re-persisting an unchanged route version does not duplicate child rows.

Existing route version, schedule, KML, and CLI tests must continue to pass.
