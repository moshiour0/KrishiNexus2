# NASA data catalog and integration boundaries

This is the crop-rotation data scope, not an inventory of every NASA archive. A product is integrated only when its units, dates, quality rules, fallback, and effect on the decision are explicit.

| NASA source | Decision role | Current path | Quality / interpretation |
|---|---|---|---|
| NASA POWER daily point weather | Temperature, humidity, wind, shortwave radiation, and rainfall drive reference ET and crop water balance | Live Daily API with retry, bounded gap filling, expiring cache, and labeled stale/synthetic fallback | Parameter-specific latency; seven-day request buffer avoids treating incomplete recent records as complete |
| SMAP SPL3/SPL4 soil moisture | Initial root-zone water state and model residual evidence | AppEEARS point sample when an available collection/layer is exposed; CSV import fallback | L3 recommended quality flags are applied where present; assimilated L4 values are disclosed separately |
| MODIS MOD16 ET | Observed ET evidence against modeled crop ET | AppEEARS point sample; 8-day interval overlap with the crop schedule | MODLAND quality bits must identify good quality; fill values rejected; interval ET converted to daily mean |
| NASA/USGS HLS vegetation indices | In-season crop canopy/vegetation evidence | AppEEARS HLS VI point sample | Uses provider cloud/shadow mask; applies returned HLS QA bits when available and reports the QA state |
| GPM IMERG Final | Satellite rainfall comparison/replacement where exposed | Optional AppEEARS daily product discovery | Product availability varies; POWER rainfall remains a separately labeled fallback. Do not treat preliminary/late-run estimates as final without a distinct validation path |
| NASA NEX-GDDP-CMIP6 | Mid-century heat, rainfall, humidity, wind, and radiation scenario deltas | Coordinate-matched daily CSV or optional Google Earth Engine `NASA/GDDP-CMIP6` | GEE uses model-weighted monthly climatology for 1995–2014 vs 2041–2060 and SSP2-4.5/SSP5-8.5. Applied to a daily analogue, not a native future daily weather sequence |

## Google Earth Engine computation

Earth Engine is the compute/access path; it is not itself a NASA dataset. For each point, the adapter filters the NASA NEX-GDDP-CMIP6 public collection by scenario and period, masks physically impossible values, averages daily values within each model, then averages available model means for each calendar month. It reduces the six weather bands at the collection's approximately 27.8 km pixel scale and caches the resulting monthly climate signals for seven days when the instance cache persists.

Conversions follow the catalog units: Kelvin temperature differences equal Celsius temperature differences; precipitation rate in kg/m²/s is converted to mm/day before forming a ratio; shortwave radiation ratios preserve units; relative humidity deltas are applied in percentage points and bounded to 0–100%; wind and solar ratios are applied to the daily analogue. A precipitation ratio is left unavailable when its historical baseline is too close to zero, and the dated daily rain values are retained for that month. All results must be validated against Bangladesh-relevant observations before recommendation weights or national claims change.

## Candidates for a later validated release

NASA products that may add value, but are not currently decision inputs, include MODIS land-surface temperature (day/night, with product QA), MODIS LAI/FPAR (with retrieval and cloud QA), and additional GPM/SMAP collection variants. They should be added only with product-specific QA, sampling cadence, scale factors, citation, performance budget, and a demonstrated contribution beyond the current HLS/POWER/SMAP/MOD16 evidence. This keeps overlapping products from silently double-counting the same signal.

Do not relabel agency/farm soil samples, Bangladesh crop calendars, agroecological zone maps, yield records, or field trials as NASA data. Their licensing and validation belong in the local-data readiness record.
