# V3 data folder

Optional files:

```text
data/v3/
├── field.geojson      # Polygon, MultiPolygon or FeatureCollection
├── soil.json           # SoilProfile-compatible JSON
├── gpm.csv             # date,gpm_rain_mm
├── smap.csv            # date,smap_surface_m3_m3,smap_rootzone_m3_m3,smap_product,smap_qa
├── hls.csv             # date,ndvi,evi,ndmi
├── modis_et.csv        # date,modis_et_mm,modis_et_qc,modis_et_period_days
├── soil_points.csv     # licensed, provenance-rich Bangladesh soil sample points
├── ssp245.csv          # date,tmax_c,tmin_c,rh_mean_pct,wind_2m_ms,solar_rad_mj_m2_day,rain_mm
└── ssp585.csv          # same schema
```

NASA POWER cache files are created automatically in `data/v3/cache/` when live API mode is enabled. A cache entry expires after 12 hours by default (`FIELD_SHIFT_POWER_CACHE_TTL_SECONDS` can change this); if the API fails, an expired entry can be used as stale data and is labeled as such. Missing values are interpolated only when both the overall missing fraction and longest consecutive gap remain under their limits.

The CSV files remain supported as offline/manual input. When `FIELD_SHIFT_APPEEARS_USER` and `FIELD_SHIFT_APPEEARS_PASSWORD` are configured as server-side secrets, `fieldshift.v3.appeears` discovers and samples currently available SMAP, MODIS MOD16, and HLS vegetation-index products. It also uses GPM IMERG only if a daily IMERG layer is available in the AppEEARS catalog. MOD16 is selected only with its QC layer and retains only MODLAND_QC=0 values; its 8-day daily mean is matched to overlapping crop days. SMAP L3 values require recommended-quality retrieval flags (0 or 8); SMAP L4 is identified separately because sampled geophysical fields do not expose that L2/L3 flag. HLS VI uses provider cloud/shadow masking, and decodes its QA layer when AppEEARS exposes it. The evidence drawer reports each source's QA state.

AppEEARS requests are asynchronous: pending task IDs are retained locally and resumed on the next analysis; successful results are cached for seven days. On Vercel these cache files may disappear when a serverless instance is recycled, so this is not a durable national observation store. Values that are missing, cloud-masked, unavailable, or not offered are never replaced with synthetic satellite measurements.

NASA NEX-GDDP-CMIP6 is still file-based. Its missing-scenario fallback is a labeled diagnostic delta, not a NASA projection. Confirm collection-specific quality rules, point-sample units, coverage, and date latency before weighting these observations for farmer recommendations.

For manual MOD16 rows, include `modis_et_qc`; rows without that flag or with MODLAND_QC bits other than 0 are ignored. `modis_et_period_days` defaults to 8 for MOD16 data. For manual SMAP L3 rows, include `smap_product` and `smap_qa`; only recommended flags 0 and 8 are accepted. Identify SMAP L4 rows as `SPL4SMGP...`. HLS VI should come from the NASA HLS-VI product or include its decoded `hls_qa` field.

The bundled soil profile applies only near the configured Mymensingh pilot point. For other coordinates it is not copied. Supply a field test/report or a verified local profile. Licensed point samples can be added to `soil_points.csv` using [`soil_points_template.csv`](../../docs/v3/soil_points_template.csv); the engine selects only a valid nearest sample within `FIELD_SHIFT_SOIL_POINT_MAX_DISTANCE_KM` (default 1 km), records source/date/license, and reports unavailable when none is close enough. SoilGrids is opt-in (`FIELD_SHIFT_SOILGRIDS=1`) and its beta REST endpoint may be unavailable.
