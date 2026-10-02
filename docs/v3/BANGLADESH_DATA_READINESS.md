# Bangladesh-wide data readiness

## What works without local-agency data

| Input | Current path | Status / limit |
|---|---|---|
| Daily weather and rainfall | NASA POWER Daily point API, requested at each field coordinate | Automatic, global point coverage, latency varies by parameter; not an instantaneous feed |
| Field soil measurements | Form fields or `data/v3/soil.json` | Manual/field supplied, carries provenance |
| Bangladesh soil sample points | `data/v3/soil_points.csv` canonical import | Loader ready; no nationwide agency/farmer dataset is bundled or verified |
| SoilGrids | Optional point REST adapter | Modeled global soil estimate; beta endpoint is currently reported paused by ISRIC |
| Crop library and decision thresholds | `config/crops_v3.yaml` and `config/region_mymensingh_v3.yaml` | Mymensingh pilot only; not nationally calibrated |
| Future climate scenarios | Local NEX-GDDP-CMIP6 CSVs, or optional authenticated Google Earth Engine retrieval of NASA NEX-GDDP-CMIP6 | GEE uses multi-model monthly climate signals; it needs Google Cloud/Earth Engine credentials. Missing projection inputs remain explicitly labeled diagnostic stress tests |

## NASA source connectors and remaining setup

| Product | Current ingestion | Blockers before recommendations can rely on it |
|---|---|---|
| GPM IMERG | Optional AppEEARS product discovery; CSV fallback | Needs Earthdata credentials and a daily IMERG layer in the current AppEEARS catalog; otherwise remains unavailable. NASA POWER precipitation remains separately labeled fallback evidence. |
| SMAP | AppEEARS point task for an available current collection; CSV fallback | L3 recommended retrieval flags 0/8 are applied; L4 root-zone geophysical values are separately labeled as assimilated and not retrieval-flag filtered. Verify local samples. |
| HLS | AppEEARS HLS vegetation-index point task; CSV fallback | Provider cloud/shadow masking is retained; when QA is returned, cloud, adjacency, shadow, snow/ice, water, and highest-aerosol flags are filtered. Verify local coverage. |
| MODIS MOD16 | AppEEARS point task for MOD16; CSV fallback | ET_QC_500m is requested and only MODLAND_QC=0 observations are retained. Each 8-day composite is matched across its crop-season overlap. |
| NEX-GDDP-CMIP6 | Daily CSV files or optional GEE access to `NASA/GDDP-CMIP6` | GEE calculates 1995–2014 vs 2041–2060 monthly multi-model climate signals for SSP2-4.5/SSP5-8.5 and adjusts a daily analogue. It is not native daily forecasting; enable Earth Engine server credentials to activate live retrieval |

## Safe expansion sequence

1. Keep farmer soil-test values authoritative and distinguish them from remotely modeled soil maps.
2. Add each NASA source as an isolated adapter with its collection/product id, access method, units, temporal and spatial resolution, quality flags, citation, and failure behavior.
3. Store extracted records durably outside a Vercel function's temporary filesystem; key them by product, location/grid cell, date, and version.
4. Add scheduled refreshes with source-specific lag windows. Keep observed, modeled, cached, stale, synthetic, and missing evidence distinguishable.
5. Validate a small test set across Bangladesh agroecological zones before changing recommendation weights or calling the pack nationwide-ready.
6. Add local agency data only after receiving permission, terms of use, metadata, units, spatial coverage, dates, and a named technical contact.

The current UI reports disconnected or unavailable products as `not_configured` or `unavailable`. AppEEARS results are only live after valid server-side Earthdata credentials are configured. A pending request is reported as pending and resumed on the next analysis. The AppEEARS and GEE caches are instance-local and temporary on Vercel; durable shared storage and broader Bangladesh field calibration remain necessary before unattended nationwide operation. Synthetic climate deltas are not NASA projections.

## Soil sample import and data governance

The engine accepts `data/v3/soil_points.csv` as a provenance-rich point dataset. Copy the header-only [`soil_points_template.csv`](soil_points_template.csv), preserve source organization, sample date, source URL, and license/terms for every sample, and use the canonical field names and units in that template. The nearest sample is applied only within a configurable radius (`FIELD_SHIFT_SOIL_POINT_MAX_DISTANCE_KM`, default 1 km); farther points are never generalized to a district or upazila. Field-entered soil results remain higher priority. Do not publish identifiable farmer or field data without permission and suitable access controls.

This import path makes future institutional files usable; it does not supply Bangladesh-wide soil coverage. A national dataset, permissions, metadata reconciliation, quality checks, and calibration against known field samples are still required.
