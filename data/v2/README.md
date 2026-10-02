# Field Shift V2 data drop folder

The engine does not require BAU data to run. Add better evidence here when it becomes available.

## Optional files

`gpm.csv`

```text
date,gpm_rain_mm
2026-01-01,2.3
```

`smap.csv` should be named `smap.csv` and can contain:

```text
date,smap_surface_m3_m3,smap_rootzone_m3_m3
2026-01-01,0.29,0.31
```

`hls.csv`

```text
date,ndvi,evi,ndmi
2026-01-01,0.62,0.38,0.21
```

`modis_et.csv`

```text
date,modis_et_mm
2026-01-01,4.8
```

`ssp245.csv` / `ssp585.csv`

```text
date,tmax_c,tmin_c,rain_mm,rh_mean_pct,wind_2m_ms,solar_rad_mj_m2_day
2026-01-01,26.1,14.2,3.4,74,1.8,16.7
```

## Provenance rule

Observed, satellite-derived, NASA-modelled, farmer-entered, literature-derived, estimated and synthetic data are never silently interchangeable. The engine carries source type and confidence into the run registry.

`field.geojson`

A Polygon or MultiPolygon field boundary. V2 uses the boundary centroid for point-based weather queries and preserves the polygon in the field object for future field-level remote-sensing aggregation.

`soil.json`

A structured local soil profile using the fields defined in `fieldshift/v2/models.py`.
