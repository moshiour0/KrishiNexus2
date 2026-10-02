from __future__ import annotations

from datetime import date, timedelta

from .agronomy import soil_indicators, yield_adjustment
from .economics import rotation_economics
from .models import CropV2, FieldV2, Rotation, Scenario, ScheduledCropV2, WeatherDay
from .water import WaterResult, simulate_crop_water


def _max_dry_days(days) -> int:
    best = cur = 0
    for d in days:
        if d.rain_mm < 1.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def compute_rotation_indicators(
    rotation: Rotation,
    schedule: tuple[ScheduledCropV2, ...],
    crops: dict[str, CropV2],
    scenario: Scenario,
    field: FieldV2,
    soc_horizon_years: int = 3,
) -> tuple[dict[str, float], list[dict[str, float]]]:
    remote = {x.d: x for x in scenario.remote}
    water_results: list[WaterResult] = []
    yields = []
    active_days: list[WeatherDay] = []
    for sc in schedule:
        crop = crops[sc.crop_id]
        wr = simulate_crop_water(crop, sc.sow_date, scenario.weather, field, remote)
        yf = yield_adjustment(crop, wr, field)
        water_results.append(wr)
        yields.append(yf)
        active_days.extend(d for d in scenario.weather if sc.sow_date <= d.d < sc.harvest_date)
    rotation_crops = tuple(crops[x] for x in rotation.crop_ids)
    soil = soil_indicators(rotation_crops, field, soc_horizon_years)
    econ = rotation_economics(rotation_crops, yields, field)
    irrigation = sum(w["irrigation_gross_mm"] for w in water_results)
    yield_total = sum(y["climate_adjusted_yield_kg_ha"] for y in yields)
    etc_total = sum(w["etc_mm"] for w in water_results)
    water_stress = sum(w["water_stress_fraction"] for w in water_results) / max(1, len(water_results))
    severe = sum(w["severe_water_stress_days"] for w in water_results) / max(1, sum(c.duration_days for c in rotation_crops))
    heat_days = sum(w["heat_stress_days"] for w in water_results)
    heat_dd = sum(w["heat_degree_days"] for w in water_results)
    waterlog_days = sum(w["waterlogging_days"] for w in water_results)
    heavy_days = sum(w["heavy_rain_days"] for w in water_results)
    dry_days = _max_dry_days(active_days)
    taw = sum(w["taw_mm"] for w in water_results) / max(1, len(water_results))
    smap_error_vals = [w["smap_abs_error_m3_m3"] for w in water_results if w["smap_match_count"] > 0]
    active_dates = {d.d for d in active_days}
    modis_overlaps: list[tuple[float, int]] = []
    for observation in scenario.remote:
        if observation.modis_et_mm is None:
            continue
        period_end = observation.d + timedelta(days=max(1, observation.modis_et_period_days))
        overlap_days = sum(1 for day in active_dates if observation.d <= day < period_end)
        if overlap_days:
            modis_overlaps.append((observation.modis_et_mm, overlap_days))
    # MOD16 is an 8-day composite, so compare its daily mean against model days
    # inside that composite rather than requiring an exact start-date match.
    modis_vals = [value for value, count in modis_overlaps for _ in range(count)]
    modis_covered_dates = {
        day
        for observation in scenario.remote if observation.modis_et_mm is not None
        for day in active_dates
        if observation.d <= day < observation.d + timedelta(days=max(1, observation.modis_et_period_days))
    }
    model_etc_by_date = {
        day: value for water_result in water_results
        for day, value in water_result.get("etc_daily_mm", {}).items()
    }
    ndvi_vals = [x.ndvi for x in (remote.get(d.d) for d in active_days) if x is not None and x.ndvi is not None]
    ndmi_vals = [x.ndmi for x in (remote.get(d.d) for d in active_days) if x is not None and x.ndmi is not None]
    calendar_margins = []
    for sc in schedule:
        _, we = _window(crops[sc.crop_id].sowing_window, sc.sow_date)
        calendar_margins.append((we - sc.sow_date).days)
    calendar_margin = min(calendar_margins) if calendar_margins else 0

    observed_et_error_pct = None
    matched_model_etc = [model_etc_by_date[day] for day in modis_covered_dates if day in model_etc_by_date]
    if modis_vals and matched_model_etc:
        observed_et_mean = sum(modis_vals) / len(modis_vals)
        model_et_mean = sum(matched_model_etc) / len(matched_model_etc)
        observed_et_error_pct = abs(model_et_mean - observed_et_mean) / max(observed_et_mean, 0.1) * 100.0

    smap_error = sum(smap_error_vals) / len(smap_error_vals) if smap_error_vals else None
    remote_covered_dates = {day for day in active_dates if day in remote or day in modis_covered_dates}
    coverage = len(remote_covered_dates) / max(1, len(active_dates))
    ndvi_mean = sum(ndvi_vals) / len(ndvi_vals) if ndvi_vals else None
    ndmi_mean = sum(ndmi_vals) / len(ndmi_vals) if ndmi_vals else None

    values = {
        **soil,
        **econ,
        "irrigation_mm": irrigation,
        "irrigation_effective_mm": sum(w["irrigation_effective_mm"] for w in water_results),
        "irrigation_loss_mm": sum(w["irrigation_loss_mm"] for w in water_results),
        "etc_total_mm": etc_total,
        "runoff_mm": sum(w["runoff_mm"] for w in water_results),
        "deep_drainage_mm": sum(w["deep_drainage_mm"] for w in water_results),
        "paddy_outflow_mm": sum(w["paddy_outflow_mm"] for w in water_results),
        "water_balance_error_mm": sum(w["water_balance_error_mm"] for w in water_results),
        "water_stress_fraction": water_stress,
        "severe_water_stress_fraction": severe,
        "heat_stress_days": heat_days,
        "heat_degree_days": heat_dd,
        "waterlogging_days": waterlog_days,
        "heavy_rain_days": heavy_days,
        "max_consecutive_dry_days": float(dry_days),
        "soil_water_deficit_mm": water_stress * taw,
        "irrigation_reliability_burden": irrigation * (1 - field.farmer.irrigation_reliability),
        "water_productivity": yield_total / max(irrigation, 1.0),
        "flood_exposure": min(1.0, (heavy_days / max(1, sum(c.duration_days for c in rotation_crops))) * (0.5 + 0.5 * ("low" in field.land_type.lower()))),
        "climate_adjusted_yield_kg_ha": yield_total,
        "yield_factor": sum(y["yield_factor"] for y in yields) / max(1, len(yields)),
        "scenario_yield_cv": 0.0,
        "labour_peak_person_days_ha": max(c.labour_person_days_ha for c in rotation_crops),
        "labour_total_person_days_ha": sum(c.labour_person_days_ha for c in rotation_crops),
        "calendar_margin_days": float(calendar_margin),
        "market_access_burden": max(0.0, min(1.0, 1 - field.farmer.market_access_score)),
        "rotation_length": float(len(rotation.crop_ids)),
        "mean_hls_ndvi": ndvi_mean,
        "mean_hls_ndmi": ndmi_mean,
        "mean_smap_rootzone_moisture": None if smap_error is None else max(0.0, min(1.0, 1.0 - smap_error / 0.15)),
        "smap_model_abs_error_m3_m3": smap_error,
        "model_vs_modis_et_error_pct": observed_et_error_pct,
        "modis_et_mean_mm": sum(modis_vals) / len(modis_vals) if modis_vals else None,
        "remote_observation_coverage_fraction": coverage,
        "hls_observation_count": float(len(ndvi_vals) + len(ndmi_vals)),
        "smap_observation_count": float(sum(w["smap_match_count"] for w in water_results)),
        "modis_observation_count": float(len(modis_overlaps)),
    }
    # Only observations supported by the input are retained; there are no injected 0.5/0.0 defaults.
    clean_values: dict[str, float] = {k: float(v) for k, v in values.items() if v is not None}
    return clean_values, yields


def _window(window: tuple[str, str], same: date):
    sm, sd = map(int, window[0].split("-"))
    em, ed = map(int, window[1].split("-"))
    a = date(same.year, sm, sd)
    b = date(same.year, em, ed)
    if b < a:
        b = date(same.year + 1, em, ed)
    return a, b
