from __future__ import annotations

import copy
import csv
import datetime as dt
import json
import math
import os
import random
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import yaml

from .appeears import appeears_point_timeseries, credentials_configured
from .economics import draw_crop_parameters
from .explain import explain
from .gee import apply_monthly_deltas, nex_gddp_monthly_deltas
from .indicators import compute_rotation_indicators
from .models import (
    CropV2,
    EngineRun,
    Evaluation,
    FarmerContext,
    FieldV2,
    IndicatorBundle,
    Provenance,
    RobustnessResult,
    Rotation,
    Scenario,
    ScenarioScore,
    SoilProfile,
    WeatherDay,
)
from .nasa import (
    align_nex_weather_to_analysis,
    load_gpm_csv,
    load_hls_csv,
    load_modis_et_csv,
    load_nex_gddp_csv,
    load_smap_csv,
    power_daily,
)
from .provenance import dataset_record, now_iso
from .rotation import generate_rotations, schedule
from .scoring import DEFAULT_DIMENSIONS, dimension_scores, percentile, rank_options, validate_weights
from .soilgrids import query_soilgrids
from .synthetic import generate_weather
from .validation import ablation_analysis, structural_validation

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "config"

DEFAULT_WEIGHTS = {
    "soil_health": 0.095,
    "nutrient_balance": 0.076,
    "soil_water_resilience": 0.095,
    "irrigation_demand": 0.095,
    "drought_risk": 0.095,
    "flood_waterlogging_risk": 0.0665,
    "heat_stress_risk": 0.076,
    "yield_potential": 0.095,
    "yield_stability": 0.076,
    "economic_return": 0.095,
    "operational_feasibility": 0.0475,
    "rotation_diversity": 0.038,
    "observation_consistency": 0.05,
}


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or CONFIG_DIR / "region_mymensingh_v3.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_crops(path: Path | None = None) -> dict[str, CropV2]:
    path = path or CONFIG_DIR / "crops_v3.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["crops"]
    out: dict[str, CropV2] = {}
    for cid, c in raw.items():
        hs = c.get("heat_sensitive_stage", {"label": "mid", "start": 0, "end": c["duration_days"]})
        out[cid] = CropV2(
            crop_id=cid, display_name=c["display_name"], family=c["family"], seasons=tuple(c["seasons"]),
            sowing_window=tuple(c["sowing_window"]), duration_days=int(c["duration_days"]), stage_days=tuple(c["stage_days"]),
            kc_ini=float(c["kc"]["ini"]), kc_mid=float(c["kc"]["mid"]), kc_end=float(c["kc"]["end"]), root_depth_m=float(c["root_depth_m"]),
            heat_sensitive_stage=(hs["label"], int(hs["start"]), int(hs["end"])), heat_threshold_c=float(c["heat_threshold_c"]),
            drought_tolerance=float(c["drought_tolerance"]), waterlogging_tolerance=float(c["waterlogging_tolerance"]),
            salinity_tolerance=float(c["salinity_tolerance"]), n_fixing=bool(c["n_fixing"]), residue_score=float(c["residue_score"]),
            yield_kg_ha=float(c["yield_kg_ha"]), price_bdt_kg=float(c["price_bdt_kg"]), cost_bdt_ha=float(c["cost_bdt_ha"]),
            labour_person_days_ha=float(c["labour_person_days_ha"]), n_demand_kg_ha=float(c.get("n_demand_kg_ha", 0)),
            p_demand_kg_ha=float(c.get("p_demand_kg_ha", 0)), k_demand_kg_ha=float(c.get("k_demand_kg_ha", 0)),
            family_break_value=float(c.get("family_break_value", 0.5)), pH_range=tuple(c["pH_range"]),
            rice_paddy=bool(c.get("rice_paddy", False)), standing_water_days=float(c.get("standing_water_days", 0)),
            percolation_mm_day=float(c.get("percolation_mm_day", 0)), seepage_mm_day=float(c.get("seepage_mm_day", 0)),
            yield_stress_sens_water=float(c.get("yield_stress_sens_water", 1.0)),
            yield_stress_sens_heat=float(c.get("yield_stress_sens_heat", 1.0)),
            source_refs=tuple(c.get("source_refs", [])), review_status=c.get("review_status", "placeholder"),
            price_cv=float(c.get("price_cv", 0.12)), yield_cv=float(c.get("yield_cv", 0.10)),
            kc_cv=float(c.get("kc_cv", 0.05)), root_depth_cv=float(c.get("root_depth_cv", 0.05)),
            residue_carbon_kg_ha=float(c.get("residue_carbon_kg_ha", 5000.0)), is_cover_crop=bool(c.get("is_cover_crop", False)),
        )
    return out


SOIL_POINT_FIELDS = (
    "ph", "soc_pct", "total_n_mgkg", "available_p_mgkg", "exchangeable_k_mgkg", "ec_ds_m",
    "cec_cmolkg", "bulk_density_g_cm3", "sand_pct", "silt_pct", "clay_pct", "soil_depth_m",
    "field_capacity_v_v", "wilting_point_v_v", "drainage_class", "curve_number",
)


def _nearest_soil_point(path: Path, lat: float, lon: float, max_distance_km: float) -> tuple[SoilProfile, dict[str, Any]] | None:
    """Read the nearest consented/canonical soil sample within the configured radius."""
    if not path.exists():
        return None
    best: tuple[float, SoilProfile, dict[str, Any]] | None = None
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                sample_lat, sample_lon = float(row["latitude"]), float(row["longitude"])
                if not (-90 <= sample_lat <= 90 and -180 <= sample_lon <= 180):
                    continue
                lat1, lat2 = math.radians(lat), math.radians(sample_lat)
                dlat, dlon = lat2 - lat1, math.radians(sample_lon - lon)
                hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                distance_km = 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(hav)))
                if distance_km > max_distance_km:
                    continue
                soil_values: dict[str, Any] = {}
                for name in SOIL_POINT_FIELDS:
                    raw = (row.get(name) or "").strip()
                    if not raw:
                        continue
                    soil_values[name] = raw if name == "drainage_class" else float(raw)
                if not soil_values:
                    continue
                source = (row.get("source_organization") or "Unspecified source").strip()
                source_url = (row.get("source_url") or "").strip() or None
                sample_date = (row.get("sample_date") or "").strip() or None
                provenance = Provenance(
                    source=f"Bangladesh soil sample: {source}", source_type="observed",
                    retrieval_date=sample_date, spatial_resolution=f"field sample point; {distance_km:.2f} km from requested location",
                    temporal_resolution="sample date", citation=source_url, confidence=0.90,
                )
                soil = SoilProfile(**soil_values, provenance={name: provenance for name in soil_values})
                metadata = {
                    "distance_km": distance_km,
                    "sample_id": (row.get("sample_id") or "").strip() or "unspecified",
                    "district": (row.get("district") or "").strip() or None,
                    "upazila": (row.get("upazila") or "").strip() or None,
                    "sample_date": sample_date,
                    "source_organization": source,
                    "source_url": source_url,
                    "license": (row.get("license") or "").strip() or "not reported",
                }
                if best is None or distance_km < best[0]:
                    best = distance_km, soil, metadata
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
    if best is None:
        return None
    return best[1], best[2]


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def build_field(cfg: dict[str, Any], priorities: dict[str, float], field_override: dict[str, Any] | None = None) -> FieldV2:
    f = _deep_merge(cfg["field"], field_override or {})
    s = f.get("soil", {})
    # The bundled soil profile is a Mymensingh pilot estimate. Never silently
    # carry it to another coordinate just because a caller changed the marker.
    center = cfg.get("field", {})
    moved = (
        abs(float(f["lat"]) - float(center.get("lat", f["lat"]))) > 0.15
        or abs(float(f["lon"]) - float(center.get("lon", f["lon"]))) > 0.15
    )
    if moved:
        override_soil = (field_override or {}).get("soil")
        s = override_soil if isinstance(override_soil, dict) else {}
    farmer_cfg = f.get("farmer", {})
    soil = SoilProfile(**s)
    farmer = FarmerContext(priorities=priorities, **{k: v for k, v in farmer_cfg.items() if k != "priorities"})
    field = FieldV2(field_id=f["field_id"], lat=float(f["lat"]), lon=float(f["lon"]), area_ha=float(f["area_ha"]),
                    elevation_m=float(f.get("elevation_m", 20)), land_type=f.get("land_type", "medium highland"),
                    soil=soil, irrigation_source=f.get("irrigation_source", "unknown"), farmer=farmer,
                    previous_crop=f.get("previous_crop"))
    field.validate()
    return field


def _load_optional_remote(
    input_dir: Path,
    datasets: list[dict],
    field: FieldV2,
    start: dt.date,
    end: dt.date,
    cache_dir: Path,
    allow_live: bool = True,
) -> tuple:
    remote: list[Any] = []
    loaders = [
        ("gpm.csv", load_gpm_csv, "NASA GPM IMERG", "daily rainfall; AppEEARS can retrieve this only if a daily IMERG layer is currently offered"),
        ("smap.csv", load_smap_csv, "NASA SMAP", "soil-moisture observations; AppEEARS point sampling is available when NASA Earthdata credentials are configured"),
        ("hls.csv", load_hls_csv, "NASA HLS", "vegetation indices; AppEEARS point sampling is available when NASA Earthdata credentials are configured"),
        ("modis_et.csv", load_modis_et_csv, "NASA MODIS MOD16", "evapotranspiration; AppEEARS point sampling is available when NASA Earthdata credentials are configured"),
    ]
    for filename, loader, source_name, setup_hint in loaders:
        p = input_dir / filename
        if p.exists():
            try:
                r = loader(p)
                remote.extend(r)
                prov = r[0].provenance if r else None
                if r:
                    record = dataset_record(source_name, prov, f"{len(r)} daily/observation rows from {filename}")
                    if source_name == "NASA MODIS MOD16":
                        record.update(quality_status="applied", quality_note="CSV ingestion retained only MODLAND_QC=0 and preserved each MOD16 composite interval.")
                    elif source_name == "NASA HLS":
                        record.update(quality_status="product_specific", quality_note="Invalid HLS QA pixels are excluded when hls_qa is supplied; otherwise NASA HLS-VI cloud/shadow masking is assumed and reported.")
                    elif source_name == "NASA SMAP":
                        record.update(quality_status="product_specific", quality_note="CSV ingestion accepts SMAP L3 only with recommended retrieval flags 0/8 and requires L4 rows to identify SPL4SMGP.")
                    datasets.append(record)
                else:
                    datasets.append({"name": source_name, "status": "unavailable", "source_type": "satellite", "error": f"{filename} contains no observation rows"})
            except Exception as exc:
                datasets.append({"name": source_name, "status": "error", "source_type": "satellite", "error": str(exc)})
        else:
            datasets.append({
                "name": source_name,
                "source_type": "satellite",
                "status": "not_configured",
                "coverage": f"{setup_hint}; NASA POWER precipitation is the weather-source fallback when its API or cache is available",
                "setup_hint": (
                    f"Set FIELD_SHIFT_APPEEARS_USER and FIELD_SHIFT_APPEEARS_PASSWORD as server-side Vercel secrets "
                    f"for automatic point sampling, or provide {p.as_posix()} using its documented CSV schema."
                ),
            })
    if allow_live and credentials_configured() and start <= end:
        replace_names = {"NASA GPM IMERG", "NASA SMAP", "NASA HLS", "NASA MODIS MOD16"}
        datasets[:] = [
            row for row in datasets
            if not (row.get("name") in replace_names and row.get("status") == "not_configured")
        ]
        try:
            result = appeears_point_timeseries(
                field.lat, field.lon, start, end, cache_dir=cache_dir,
            )
            remote.extend(result.remote)
            datasets.extend(result.datasets)
        except Exception as exc:
            datasets.extend({
                "name": name,
                "source_type": "satellite",
                "status": "unavailable",
                "error": f"NASA AppEEARS point sample failed ({type(exc).__name__}); existing POWER, supplied-file, or synthetic fallback remains labelled.",
                "setup_hint": "Check NASA Earthdata Login access, the AppEEARS product catalog, and the Vercel server environment variables.",
            } for name in sorted(replace_names))
    return tuple(remote)


def _merge_remote(rows) -> tuple:
    by: dict[Any, Any] = {}
    for x in rows:
        prev = by.get(x.d)
        if prev is None:
            by[x.d] = x
            continue
        kw = {}
        for k in ("ndvi", "evi", "ndmi", "smap_surface_m3_m3", "smap_rootzone_m3_m3", "modis_et_mm", "gpm_rain_mm"):
            current = getattr(x, k)
            prior = getattr(prev, k)
            kw[k] = current if current is not None else prior
        modis_period_days = x.modis_et_period_days if x.modis_et_mm is not None else prev.modis_et_period_days
        by[x.d] = type(prev)(
            x.d, source=f"{prev.source}+{x.source}", provenance=x.provenance or prev.provenance,
            modis_et_period_days=modis_period_days, **kw,
        )
    return tuple(sorted(by.values(), key=lambda x: x.d))


def load_scenarios(field: FieldV2, year: int, input_dir: Path | None, datasets: list[dict]) -> list[Scenario]:
    input_dir = input_dir or (ROOT / "data" / "v3")
    try:
        input_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    baseline = None
    target_end = dt.date(year + 2, 12, 31)
    nasa_mode = os.getenv("FIELD_SHIFT_LIVE_NASA", "auto").lower()
    nasa_ok = nasa_mode not in {"0", "false", "off", "no"}
    if nasa_ok:
        request_start = dt.date(year, 1, 1)
        # POWER combines variables with different latency. Leave a seven-day
        # safety buffer so recent incomplete solar/met records are not filled
        # forward and presented as fresh observations.
        request_end = min(target_end, dt.datetime.now(dt.UTC).date() - dt.timedelta(days=7))
        if request_start <= request_end:
            try:
                cache_dir = Path(os.getenv("FIELD_SHIFT_CACHE_DIR", str(input_dir / "cache")))
                baseline = power_daily(field.lat, field.lon, request_start, request_end, cache_dir=cache_dir)
                source = baseline[0].source
                record = dataset_record(
                    "NASA POWER Daily weather",
                    baseline[0].provenance,
                    f"{len(baseline)} daily records, {baseline[0].d.isoformat()} to {baseline[-1].d.isoformat()}; {source}",
                )
                record["data_start_date"] = baseline[0].d.isoformat()
                record["data_end_date"] = baseline[-1].d.isoformat()
                record["retrieval_mode"] = (
                    "stale-cache" if "(stale-cache;" in source else
                    "cache" if "(cache" in source else
                    "live" if "(live" in source else "unknown"
                )
                if record["retrieval_mode"] == "stale-cache":
                    record["status"] = "stale"
                    record["fallback"] = "NASA was temporarily unavailable; a clearly marked cached NASA record was used"
                datasets.append(record)
            except Exception as exc:
                datasets.append({
                    "name": "NASA POWER Daily weather", "source_type": "observed/model-derived",
                    "status": "unavailable", "error": str(exc), "fallback": "synthetic weather",
                })
        else:
            datasets.append({
                "name": "NASA POWER Daily weather", "source_type": "observed/model-derived",
                "status": "unavailable",
                "error": "The requested analysis starts after the latest complete NASA POWER daily data window.",
                "fallback": "synthetic weather",
            })
    else:
        datasets.append({
            "name": "NASA POWER Daily weather", "source_type": "observed/model-derived",
            "status": "unavailable", "error": "Live NASA POWER fetching is disabled by FIELD_SHIFT_LIVE_NASA.",
            "fallback": "synthetic weather",
        })
    if baseline is None:
        baseline = tuple(d for i in range(3) for d in generate_weather(year + i, field.lat, field.lon, field.elevation_m, seed=42 + i))
        p = Provenance(source="Field Shift V3 stochastic weather generator", source_type="synthetic", temporal_resolution="daily", confidence=0.30)
        datasets.append(dataset_record("Synthetic fallback weather", p, f"{len(baseline)} daily records", "fallback"))
    elif baseline[-1].d < target_end:
        existing_dates = {x.d for x in baseline}
        synth_tail = [
            d for i in range(3)
            for d in generate_weather(year + i, field.lat, field.lon, field.elevation_m, seed=42 + i)
            if d.d > baseline[-1].d and d.d not in existing_dates
        ]
        if synth_tail:
            p_ext = Provenance(
                source="Field Shift V3 forward weather projection",
                source_type="synthetic",
                temporal_resolution="daily",
                confidence=0.30,
            )
            synth_weather = [
                WeatherDay(d.d, d.tmax_c, d.tmin_c, d.rh_mean_pct, d.wind_2m_ms, d.solar_rad_mj_m2_day, d.rain_mm, "synthetic-forward-projection", p_ext)
                for d in synth_tail
            ]
            baseline = tuple(list(baseline) + synth_weather)
            datasets.append(dataset_record("Forward stochastic weather extension", p_ext, f"{len(synth_weather)} projected daily records", "extension"))

    satellite_start = dt.date(year, 1, 1)
    satellite_end = min(dt.date(year + 2, 12, 31), dt.datetime.now(dt.UTC).date() - dt.timedelta(days=14))
    satellite_cache_dir = Path(os.getenv("FIELD_SHIFT_CACHE_DIR", str(input_dir / "cache")))
    remote_rows = _load_optional_remote(
        input_dir, datasets, field, satellite_start, satellite_end, satellite_cache_dir, allow_live=nasa_ok,
    )
    remote = _merge_remote(remote_rows)
    baseline_scenario = Scenario(
        "baseline",
        "NASA POWER when available; otherwise stochastic synthetic weather with explicit synthetic provenance.",
        tuple(baseline), remote, baseline[0].source, [baseline[0].provenance] if baseline[0].provenance else [],
    )
    scenarios = [baseline_scenario]

    for name, ssp in (("ssp245_midcentury", "ssp245"), ("ssp585_midcentury", "ssp585")):
        path = input_dir / f"{ssp}.csv"
        if path.exists():
            try:
                projected = load_nex_gddp_csv(path, ssp)
                w = align_nex_weather_to_analysis(projected, tuple(baseline))
                prov_list = [w[0].provenance] if w and w[0].provenance else []
                scenarios.append(Scenario(
                    name,
                    f"NASA NEX-GDDP-CMIP6 {ssp} daily climate analogue; projected years mapped to the crop-plan calendar.",
                    w, remote, w[0].source, prov_list,
                ))
                record = dataset_record(
                    f"NASA NEX-GDDP-CMIP6 {ssp}", w[0].provenance if w else None,
                    f"{len(w)} projected daily records mapped to analysis dates",
                )
                record.update(status="available", calendar_alignment="successive available projection years mapped onto plan years")
                datasets.append(record)
                continue
            except Exception as exc:
                datasets.append({
                    "name": f"NASA NEX-GDDP-CMIP6 {ssp}", "source_type": "modeled",
                    "status": "error", "error": str(exc),
                })

        cache_dir = Path(os.getenv("FIELD_SHIFT_CACHE_DIR", str(input_dir / "cache")))
        gee_result = nex_gddp_monthly_deltas(field.lat, field.lon, ssp, cache_dir)
        if gee_result.monthly is not None:
            monthly_weather = apply_monthly_deltas(tuple(baseline), gee_result.monthly)
            climate_provenance = Provenance(
                source="NASA NEX-GDDP-CMIP6 via Google Earth Engine",
                source_type="modeled",
                retrieval_date=gee_result.retrieved_at,
                spatial_resolution="0.25 degree (~27.8 km) point pixel; multi-model mean",
                temporal_resolution="monthly 1995-2014 baseline vs 2041-2060 climate signals applied to daily analogue",
                citation="https://developers.google.com/earth-engine/datasets/catalog/NASA_GDDP-CMIP6",
                confidence=0.80,
            )
            w = tuple(WeatherDay(
                d=item.d, tmax_c=item.tmax_c, tmin_c=item.tmin_c, rh_mean_pct=item.rh_mean_pct,
                wind_2m_ms=item.wind_2m_ms, solar_rad_mj_m2_day=item.solar_rad_mj_m2_day,
                rain_mm=item.rain_mm, source=item.source, provenance=climate_provenance,
            ) for item in monthly_weather)
            source_label = f"NASA NEX-GDDP-CMIP6 {ssp} via GEE ({gee_result.status})"
            scenarios.append(Scenario(
                name,
                f"NASA NEX-GDDP-CMIP6 {ssp}: 2041-2060 multi-model monthly climate signals applied to the dated daily weather analogue.",
                w, remote, source_label, [climate_provenance],
            ))
            record = dataset_record(
                f"NASA NEX-GDDP-CMIP6 {ssp} via Google Earth Engine", climate_provenance,
                "12 monthly multi-model climate signals, historical 1995-2014 vs mid-century 2041-2060",
            )
            record.update(
                status="stale" if gee_result.status == "stale-cache" else "available",
                retrieval_mode=gee_result.status,
                scenario=ssp,
                cache_age_seconds=gee_result.age_seconds,
                precipitation_unadjusted_months=[
                    month for month, values in gee_result.monthly.items() if values.get("precip_ratio") is None
                ],
                methodology="Equal-weight average within each available climate model, then multi-model monthly change factors; daily event sequence is an analogue, not a native future daily forecast.",
            )
            datasets.append(record)
            continue

        delta_t = 1.6 if ssp == "ssp245" else 2.6
        rain_mult = 0.97 if ssp == "ssp245" else 0.92
        w = tuple(type(x)(x.d, x.tmax_c + delta_t, x.tmin_c + delta_t, x.rh_mean_pct,
                          x.wind_2m_ms, x.solar_rad_mj_m2_day, x.rain_mm * rain_mult,
                          f"diagnostic-delta:{ssp}", x.provenance) for x in baseline)
        p = Provenance(source=f"Diagnostic stress-test delta {ssp}", source_type="estimated", temporal_resolution="daily", confidence=0.35)
        scenarios.append(Scenario(name, "Diagnostic stress-test delta; not a substitute for a GCM ensemble.", w, remote, "diagnostic-delta", [p]))
        datasets.append(dataset_record(f"Diagnostic scenario {ssp}", p, f"{len(w)} daily records", "fallback"))
        datasets.append({
            "name": f"NASA NEX-GDDP-CMIP6 {ssp}", "source_type": "modeled",
            "status": gee_result.status,
            "coverage": f"No {path.name} scenario file or usable GEE response was available; the selected scenario remains an explicitly labelled diagnostic stress test, not NASA projection data.",
            "setup_hint": (
                "Configure FIELD_SHIFT_GEE_PROJECT and FIELD_SHIFT_GEE_SERVICE_ACCOUNT_JSON for the server-side Earth Engine connector, "
                f"or supply a coordinate-matched {path.name} file."
            ),
            "error": gee_result.error,
        })
    return scenarios


def _unique_rotations(crops: dict[str, CropV2], cfg: dict[str, Any], field: FieldV2, year: int) -> tuple[list[Rotation], list[dict[str, str]]]:
    generated: list[Rotation] = []
    seen = set()
    search = cfg.get("search", {})
    max_crops = int(search.get("max_sequence_length", 4))
    preferred = set(field.farmer.preferred_crops)
    avoided = set(field.farmer.avoided_crops)
    for r in generate_rotations(
        crops,
        max_crops=max_crops,
        start_year=year,
        turnaround_days=int(cfg.get("constraints", {}).get("turnaround_days", 10)),
        preferred=preferred,
        avoided=avoided,
        avoid_consecutive_family=bool(search.get("avoid_consecutive_family", True)),
    ):
        if r.crop_ids not in seen:
            seen.add(r.crop_ids)
            generated.append(r)
    baseline_ids = tuple(cfg.get("baseline_rotation", []))
    if baseline_ids:
        generated.insert(0, Rotation("BASELINE", baseline_ids, "Current/baseline practice", "baseline"))

    accepted, rejected = [], []
    max_cycle = int(cfg.get("constraints", {}).get("max_cycle_days", 760))
    for r in generated:
        sch = schedule(r, crops, year, int(cfg.get("constraints", {}).get("turnaround_days", 10)), max_cycle)
        if sch is None:
            rejected.append({"rotation_id": r.rotation_id, "reason": "calendar infeasible"})
            continue
        ok, reason = _hard_constraints(r, crops, field, sch, is_baseline=r.source == "baseline")
        if ok or r.source == "baseline":
            accepted.append(r)
        else:
            rejected.append({"rotation_id": r.rotation_id, "reason": reason})
    return accepted, rejected


def _hard_constraints(r: Rotation, crops: dict[str, CropV2], field: FieldV2, schedule_tuple, *, is_baseline: bool = False) -> tuple[bool, str]:
    for cid in r.crop_ids:
        if cid in field.farmer.avoided_crops:
            return False, f"{cid}: farmer avoidance constraint failed"
        if field.soil.ph is not None and not (crops[cid].pH_range[0] <= field.soil.ph <= crops[cid].pH_range[1]):
            return False, f"{cid}: pH suitability constraint failed"
        if "low" in field.land_type.lower() and crops[cid].waterlogging_tolerance < 0.35:
            return False, f"{cid}: lowland/waterlogging constraint failed"
    total_cost = sum(crops[cid].cost_bdt_ha for cid in r.crop_ids)
    total_labour = sum(crops[cid].labour_person_days_ha for cid in r.crop_ids)
    if field.farmer.budget_bdt_ha is not None and total_cost > field.farmer.budget_bdt_ha:
        return False, f"rotation cost {total_cost:.0f} exceeds budget {field.farmer.budget_bdt_ha:.0f} BDT/ha"
    if field.farmer.labour_available_person_days_ha is not None and total_labour > field.farmer.labour_available_person_days_ha:
        return False, f"rotation labour {total_labour:.1f} exceeds available {field.farmer.labour_available_person_days_ha:.1f} person-days/ha"
    return True, ""


def _scenario_cv(indicators_by_scenario: dict[str, dict[str, float]]) -> float:
    vals = [x.get("climate_adjusted_yield_kg_ha", 0.0) for x in indicators_by_scenario.values()]
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    if m <= 0:
        return 1.0
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))
    return sd / m


def _perturb_field(field: FieldV2, rng: random.Random) -> FieldV2:
    s = field.soil
    ph = max(4.5, min(8.5, (s.ph or 6.5) + rng.gauss(0, 0.08)))
    bd = max(0.8, min(1.8, (s.bulk_density_g_cm3 or 1.35) * math.exp(rng.gauss(0, 0.04))))
    fc = s.field_capacity_v_v
    wp = s.wilting_point_v_v
    if fc is not None and wp is not None:
        mid = (fc + wp) / 2
        spread = (fc - wp) * max(0.75, 1 + rng.gauss(0, 0.08))
        fc = min(0.8, mid + spread / 2)
        wp = max(0.02, mid - spread / 2)
        if fc <= wp:
            fc, wp = s.field_capacity_v_v, s.wilting_point_v_v
    soil = replace(
        s,
        ph=ph,
        soc_pct=max(0.05, (s.soc_pct or 1.0) * math.exp(rng.gauss(0, 0.08))),
        total_n_mgkg=max(1.0, (s.total_n_mgkg or 500.0) * math.exp(rng.gauss(0, 0.10))),
        available_p_mgkg=max(0.1, (s.available_p_mgkg or 10.0) * math.exp(rng.gauss(0, 0.12))),
        exchangeable_k_mgkg=max(1.0, (s.exchangeable_k_mgkg or 100.0) * math.exp(rng.gauss(0, 0.10))),
        bulk_density_g_cm3=bd, field_capacity_v_v=fc, wilting_point_v_v=wp,
    )
    reliability = max(0.05, min(1.0, field.farmer.irrigation_reliability + rng.gauss(0, 0.04)))
    farmer = replace(field.farmer, irrigation_reliability=reliability)
    return replace(field, soil=soil, farmer=farmer)


def _parameter_monte_carlo(
    option_ids: list[str], rotations: dict[str, Rotation], schedules: dict[str, tuple], scenarios: list[Scenario], crops: dict[str, CropV2], field: FieldV2,
    dimensions: tuple[str, ...], defs: dict, priorities: dict[str, float], n_samples: int, seed: int, soc_horizon_years: int,
) -> tuple[dict[str, list[float]], dict[str, int], dict[str, list[int]]]:
    rng = random.Random(seed)
    score_samples: dict[str, list[float]] = {oid: [] for oid in option_ids}
    top_counts = {oid: 0 for oid in option_ids}
    rank_samples: dict[str, list[int]] = {oid: [] for oid in option_ids}
    for _ in range(max(1, n_samples)):
        sampled_crops = dict(crops)
        # Shared crop parameter draws ensure options using the same crop are correlated, which is more realistic than independent jitter.
        for cid, crop in crops.items():
            sampled_crops[cid] = draw_crop_parameters((crop,), rng)[0]
        sampled_field = _perturb_field(field, rng)
        scenario_scores_by_oid: dict[str, list[float]] = {oid: [] for oid in option_ids}
        for scenario in scenarios:
            raw = []
            oid_order = []
            for oid in option_ids:
                vals, _ = compute_rotation_indicators(rotations[oid], schedules[oid], sampled_crops, scenario, sampled_field, soc_horizon_years)
                raw.append(vals)
                oid_order.append(oid)
            ds = dimension_scores(raw, dimensions, defs)
            for i, oid in enumerate(oid_order):
                scenario_scores_by_oid[oid].append(sum(ds[d][i] * priorities[d] for d in dimensions))
        means = {oid: sum(scenario_scores_by_oid[oid]) / len(scenarios) for oid in option_ids}
        ordered = sorted(option_ids, key=lambda x: (-means[x], x))
        top_counts[ordered[0]] += 1
        for r, oid in enumerate(ordered, 1):
            rank_samples[oid].append(r)
            score_samples[oid].append(means[oid])
    return score_samples, top_counts, rank_samples


def run_v3(
    priorities: dict[str, float] | None = None,
    *,
    config_path: Path | None = None,
    input_dir: Path | None = None,
    year: int = 2026,
    n_weight_samples: int = 250,
    n_uncertainty_samples: int = 64,
    field_override: dict[str, Any] | None = None,
) -> EngineRun:
    cfg = load_config(config_path)
    priorities = priorities or DEFAULT_WEIGHTS.copy()
    dimensions = tuple(cfg.get("dimensions", DEFAULT_DIMENSIONS))
    dimension_definitions = cfg.get("dimension_definitions", {})
    validate_weights(priorities, dimensions)
    crops = load_crops()
    field = build_field(cfg, priorities, field_override=field_override)
    datasets: list[dict] = []

    input_dir = input_dir or (ROOT / "data" / "v3")
    if input_dir.exists():
        field_geo = input_dir / "field.geojson"
        soil_json = input_dir / "soil.json"
        soil_input = (field_override or {}).get("soil")
        soil_keys = {
            "ph", "soc_pct", "total_n_mgkg", "available_p_mgkg", "exchangeable_k_mgkg", "ec_ds_m",
            "cec_cmolkg", "bulk_density_g_cm3", "sand_pct", "silt_pct", "clay_pct", "soil_depth_m",
            "field_capacity_v_v", "wilting_point_v_v", "drainage_class", "curve_number",
        }
        supplied_soil = {
            key: value for key, value in (soil_input.items() if isinstance(soil_input, dict) else [])
            if key in soil_keys and value is not None
        }
        soil_loaded = False
        if field_geo.exists():
            try:
                data = json.loads(field_geo.read_text(encoding="utf-8"))
                geometries = []
                if data.get("type") == "FeatureCollection":
                    geometries = [f.get("geometry", {}) for f in data.get("features", [])]
                else:
                    geometries = [data.get("geometry", data)]
                coords = []
                for geom in geometries:
                    if geom.get("type") == "Polygon":
                        coords.extend([(float(y), float(x)) for x, y in geom.get("coordinates", [[]])[0]])
                    elif geom.get("type") == "MultiPolygon":
                        for poly in geom.get("coordinates", []):
                            if poly:
                                coords.extend([(float(y), float(x)) for x, y in poly[0]])
                if coords:
                    field.polygon = coords
                    field.lat = sum(p[0] for p in coords) / len(coords)
                    field.lon = sum(p[1] for p in coords) / len(coords)
                    if (
                        abs(field.lat - float(cfg.get("field", {}).get("lat", field.lat))) > 0.15
                        or abs(field.lon - float(cfg.get("field", {}).get("lon", field.lon))) > 0.15
                    ):
                        field.soil = SoilProfile(**supplied_soil)
                    field.validate()
                    datasets.append({"name": "field.geojson", "source_type": "farmer", "status": "available", "confidence": 0.95, "coverage": f"{len(coords)} boundary vertices; centroid used for gridded data"})
            except Exception as exc:
                datasets.append({"name": "field.geojson", "status": "error", "error": str(exc)})
        if supplied_soil:
            soil_source = str((field_override or {}).get("soil_data_source", "farmer-estimate"))
            lab_result = soil_source == "soil-test"
            datasets.append({
                "name": "Farmer-entered soil test values" if lab_result else "Farmer-reported soil profile",
                "source": "Values entered by the farmer; not independently verified",
                "source_type": "farmer",
                "status": "available",
                "confidence": 0.82 if lab_result else 0.58,
                "coverage": "Field-entered fields: " + ", ".join(sorted(supplied_soil)),
            })
        if not supplied_soil and soil_json.exists():
            try:
                raw_soil = json.loads(soil_json.read_text(encoding="utf-8"))
                field.soil = SoilProfile(**raw_soil)
                field.validate()
                datasets.append({"name": "soil.json", "source_type": "observed", "status": "available", "confidence": 0.95, "coverage": "field soil profile"})
                soil_loaded = True
            except Exception as exc:
                datasets.append({"name": "soil.json", "status": "error", "error": str(exc)})
        if not supplied_soil and not soil_loaded:
            try:
                radius_km = max(0.0, float(os.getenv("FIELD_SHIFT_SOIL_POINT_MAX_DISTANCE_KM", "1.0")))
                nearest = _nearest_soil_point(input_dir / "soil_points.csv", field.lat, field.lon, radius_km)
                if nearest is not None:
                    point_soil, point_meta = nearest
                    field.soil = point_soil
                    field.validate()
                    location = ", ".join(x for x in (point_meta["upazila"], point_meta["district"]) if x)
                    datasets.append({
                        "name": "Bangladesh soil sample points",
                        "source": point_meta["source_organization"],
                        "source_type": "observed",
                        "status": "available",
                        "confidence": 0.90,
                        "coverage": (
                            f"Nearest sample {point_meta['sample_id']} is {point_meta['distance_km']:.2f} km away"
                            + (f" ({location})" if location else "")
                            + f"; sample date: {point_meta['sample_date'] or 'not reported'}"
                        ),
                        "retrieval_date": point_meta["sample_date"],
                        "spatial_resolution": f"sample point; radius limited to {radius_km:g} km",
                        "temporal_resolution": "sample date",
                        "citation": point_meta["source_url"],
                        "license": point_meta["license"],
                    })
                    soil_loaded = True
                elif (input_dir / "soil_points.csv").exists():
                    datasets.append({
                        "name": "Bangladesh soil sample points", "source_type": "observed", "status": "unavailable",
                        "coverage": f"No valid sample within {radius_km:g} km of the field; no distant sample was substituted.",
                    })
            except Exception as exc:
                datasets.append({"name": "Bangladesh soil sample points", "source_type": "observed", "status": "error", "error": str(exc)})
        if not supplied_soil and not soil_loaded and os.getenv("FIELD_SHIFT_SOILGRIDS", "0").lower() in {"1", "true", "yes", "on"}:
            try:
                grid_profile = query_soilgrids(field.lat, field.lon)
                field.soil = grid_profile
                field.validate()
                prov = next(iter(field.soil.provenance.values()), None)
                if prov is not None:
                    datasets.append(dataset_record("ISRIC SoilGrids 2.0", prov, "point profile", "available"))
                else:
                    datasets.append({"name": "ISRIC SoilGrids 2.0", "status": "available", "source_type": "modeled", "coverage": "point profile"})
                soil_loaded = True
            except Exception as exc:
                datasets.append({"name": "ISRIC SoilGrids 2.0", "status": "unavailable", "source_type": "modeled", "error": str(exc), "fallback": "field soil report, Mymensingh pilot estimate only at its pilot coordinates, or clearly labeled incomplete soil profile"})
        if not soil_loaded:
            if supplied_soil:
                # Merge field measurements into the configured estimate only
                # inside the Mymensingh pilot. Other locations start blank.
                current_soil = field.soil
                field.soil = replace(current_soil, **supplied_soil)
            pilot_soil = not (
                abs(field.lat - float(cfg.get("field", {}).get("lat", field.lat))) > 0.15
                or abs(field.lon - float(cfg.get("field", {}).get("lon", field.lon))) > 0.15
            )
            if not pilot_soil:
                field.soil.provenance = {}
            if os.getenv("FIELD_SHIFT_SOILGRIDS", "0").lower() not in {"1", "true", "yes", "on"}:
                datasets.append({
                    "name": "ISRIC SoilGrids 2.0",
                    "source_type": "modeled",
                    "status": "not_configured",
                    "coverage": "The point adapter is opt-in and its REST endpoint is currently reported as paused by ISRIC; no SoilGrids values were used",
                    "setup_hint": "Use a local soil test or verified national soil layer; re-enable the SoilGrids adapter only after checking ISRIC service status.",
                    "citation": "https://docs.isric.org/globaldata/soilgrids/",
                })
            datasets.append({
                "name": "Configured Mymensingh soil profile" if pilot_soil else "Field soil profile not supplied",
                "source_type": "estimated",
                "status": "fallback",
                "confidence": 0.35 if pilot_soil else 0.10,
                "coverage": (
                    "Mymensingh pilot estimate used for unentered soil properties" if pilot_soil
                    else "No Bangladesh-wide field soil dataset was supplied; Mymensingh soil values were excluded at this location"
                ),
                "fallback": "Enter a soil-test report or a clearly labeled field estimate; the model uses generic physical defaults for missing properties",
            })

    scenarios = load_scenarios(field, year, input_dir, datasets)
    rotations, rejected = _unique_rotations(crops, cfg, field, year)
    rotation_map = {r.rotation_id: r for r in rotations}
    indicator_matrix: dict[str, dict[str, list[float]]] = {s.name: {} for s in scenarios}
    bundles: dict[str, dict[str, IndicatorBundle]] = {s.name: {} for s in scenarios}
    schedules: dict[str, tuple] = {}
    for r in rotations:
        sch = schedule(r, crops, year, int(cfg.get("constraints", {}).get("turnaround_days", 10)), int(cfg.get("constraints", {}).get("max_cycle_days", 760)))
        if sch is None:
            continue
        schedules[r.rotation_id] = sch
        for s in scenarios:
            values, _ = compute_rotation_indicators(r, sch, crops, s, field, int(cfg.get("soil_model", {}).get("horizon_years", 3)))
            if (
                r.source != "baseline"
                and field.farmer.water_available_mm_season is not None
                and s.name == "baseline"
                and values.get("irrigation_mm", 0.0) > field.farmer.water_available_mm_season
            ):
                rejected.append({"rotation_id": r.rotation_id, "reason": f"gross irrigation {values.get('irrigation_mm', 0.0):.1f} mm exceeds available {field.farmer.water_available_mm_season:.1f} mm"})
                break
            bundles[s.name][r.rotation_id] = IndicatorBundle(r.rotation_id, s.name, values, {})
        else:
            continue
        schedules.pop(r.rotation_id, None)
    for rid in schedules:
        by_s = {s: bundles[s][rid].values for s in bundles}
        cv = _scenario_cv(by_s)
        yields = [x.get("climate_adjusted_yield_kg_ha", 0.0) for x in by_s.values()]
        baseline_yield = by_s.get("baseline", {}).get("climate_adjusted_yield_kg_ha", 0.0)
        min_ratio = min(yields) / max(baseline_yield, 1e-9) if yields and baseline_yield > 0 else None
        for sc_name in bundles:
            bundles[sc_name][rid].values["scenario_yield_cv"] = cv
            if min_ratio is not None:
                bundles[sc_name][rid].values["scenario_yield_min_ratio"] = min(1.0, max(0.0, min_ratio))

    for s in scenarios:
        arr = [bundles[s.name][rid].values for rid in schedules]
        indicator_matrix[s.name] = dimension_scores(arr, dimensions, dimension_definitions)

    option_ids = list(schedules.keys())
    if not option_ids:
        raise ValueError("No feasible rotation remains after calendar, agronomic, resource, and farmer constraints.")
    score_samples, mc_top_counts, mc_rank_samples = _parameter_monte_carlo(
        option_ids, rotation_map, schedules, scenarios, crops, field, dimensions, dimension_definitions, priorities,
        n_uncertainty_samples, int(cfg.get("uncertainty", {}).get("seed", 42)), int(cfg.get("soil_model", {}).get("horizon_years", 3)),
    )
    ranked = rank_options(
        option_ids, indicator_matrix, priorities,
        risk_tolerance=field.farmer.risk_tolerance,
        n_weight_samples=n_weight_samples,
        uncertainty_samples=score_samples,
        seed=int(cfg.get("uncertainty", {}).get("seed", 42)),
    )
    for oid in option_ids:
        ranked["results"][oid]["top1_probability"] = mc_top_counts[oid] / max(1, n_uncertainty_samples)
        ranked["results"][oid]["rank_mean"] = sum(mc_rank_samples[oid]) / max(1, len(mc_rank_samples[oid]))
        ranked["results"][oid]["rank_p90"] = percentile([float(x) for x in mc_rank_samples[oid]], 0.90)
    ordered = sorted(option_ids, key=lambda oid: (-ranked["results"][oid]["risk_adjusted_score"], ranked["results"][oid]["max_regret"], oid))

    baseline_values = bundles["baseline"]["BASELINE"].values if "baseline" in bundles and "BASELINE" in bundles["baseline"] else None
    evaluations = []
    for oid in ordered:
        scores = ranked["results"][oid]
        scenario_scores = {}
        for s in scenarios:
            idx = option_ids.index(oid)
            dim = {d: indicator_matrix[s.name][d][idx] for d in dimensions}
            overall = sum(dim[d] * priorities[d] for d in dimensions)
            scenario_scores[s.name] = ScenarioScore(s.name, dim, overall)
        robustness = RobustnessResult(
            score_mean=scores["mean_score"], score_p10=scores["score_p10"], score_p50=scores["score_p50"], score_p90=scores["score_p90"],
            top1_probability=scores["top1_probability"], rank_mean=scores["rank_mean"], rank_p90=scores["rank_p90"],
            regret_max=scores["max_regret"], pareto_optimal=scores["pareto_optimal"], sensitivity={},
            score_std=scores["score_std"], risk_adjusted_score=scores["risk_adjusted_score"], rank_samples=n_uncertainty_samples,
        )
        indicator_values = bundles["baseline"][oid].values if "baseline" in bundles and oid in bundles["baseline"] else bundles[scenarios[0].name][oid].values
        ev = explain(
            rotation_map[oid].label, scores["dimension_scores"], indicator_values, baseline_values, scores["scenario_scores"], datasets,
            constraint_notes=_constraint_notes(rotation_map[oid], crops, field),
        )
        evaluations.append(Evaluation(rotation_map[oid], schedules[oid], {s: bundles[s][oid] for s in bundles}, scenario_scores, robustness, ev))

    validation = structural_validation(evaluations, dimensions, balance_tolerance_mm=float(cfg.get("validation", {}).get("water_balance_tolerance_mm", 1e-6)))
    ablation = ablation_analysis(evaluations, priorities, "BASELINE") if evaluations else {}
    capabilities = [
        "NASA POWER global daily point ingestion for the selected field coordinates, with retry, expiring disk cache, stale-cache fallback, and bounded gap interpolation",
        "NASA GPM IMERG AppEEARS point-sampling discovery when a daily layer is available; otherwise labelled CSV/fallback path",
        "NASA SMAP AppEEARS point sampling for current available collections, with CSV fallback and explicit missing-data state",
        "NASA HLS vegetation-index AppEEARS point sampling for current available products, with CSV fallback",
        "NASA MODIS MOD16 AppEEARS point sampling with 8-day ET converted to interval mean, with CSV fallback",
        "NASA NEX-GDDP-CMIP6 coordinate-matched CSV ingestion with explicitly labelled diagnostic fallback when projection files are absent",
        "FAO-56 Penman-Monteith ET0 with golden-test coverage",
        "SCS-CN runoff plus root-zone water balance with irrigation loss, drainage and mass-conservation checks",
        "Dimensionally consistent nutrient stock conversion using bulk density x depth",
        "Multi-year SOC trajectory proxy with explicit coefficients and horizon",
        "Absolute, config-audited feature scales; no candidate-set min-max normalization",
        "Input-parameter Monte Carlo propagating crop, soil, Kc, root-depth and economic uncertainty",
        "Risk tolerance, budget, labour and water hard constraints are enforced for generated plans",
        "Calendar-aware rotation generation with preferred-first and avoided crops without duplicate traversal",
        "Provenance-aware evidence chain and a usable HTTP API + responsive web UI",
    ]
    notes = [
        "V3 uncertainty is input-level Monte Carlo, not score jitter.",
        "Absolute feature scales are editable and auditable; values outside a scale are clipped rather than re-based on the candidate set.",
        "Soil carbon is a lightweight two-pool trajectory proxy and still requires local calibration before field deployment.",
        "Diagnostic SSP delta scenarios are stress tests, not equivalent to a multi-GCM climate ensemble.",
        "Production calibration/validation against local yield, soil and satellite observations remains an evidence task, not something inferable from the code alone.",
    ]
    return EngineRun(
        engine_version="3.0.0",
        generated_at=now_iso(), field_id=field.field_id, objective_weights=priorities,
        scenarios=[s.name for s in scenarios], evaluations=evaluations, rejected=rejected,
        dataset_registry=datasets, validation=validation, ablation=ablation, system_capabilities=capabilities,
        scientific_notes=notes,
    )


def _constraint_notes(rotation: Rotation, crops: dict[str, CropV2], field: FieldV2) -> list[str]:
    notes = []
    cost = sum(crops[c].cost_bdt_ha for c in rotation.crop_ids)
    labour = sum(crops[c].labour_person_days_ha for c in rotation.crop_ids)
    if field.farmer.budget_bdt_ha is not None:
        notes.append(f"Estimated input cost: {cost:.0f} BDT/ha; budget: {field.farmer.budget_bdt_ha:.0f} BDT/ha.")
    if field.farmer.labour_available_person_days_ha is not None:
        notes.append(f"Estimated labour: {labour:.1f} person-days/ha; availability: {field.farmer.labour_available_person_days_ha:.1f}.")
    if field.farmer.water_available_mm_season is not None:
        notes.append(f"Seasonal gross irrigation ceiling: {field.farmer.water_available_mm_season:.0f} mm.")
    return notes


def save_run(run: EngineRun, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(run), indent=2, default=str), encoding="utf-8")
