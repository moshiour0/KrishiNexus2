from __future__ import annotations
from datetime import date
from .models import CropV2, FieldV2, RemoteDay, Rotation, ScheduledCropV2, Scenario
from .water import simulate_crop_water
from .agronomy import yield_adjustment, soil_indicators
from .economics import rotation_economics


def _max_dry_days(days) -> int:
    best = cur = 0
    for d in days:
        if d.rain_mm < 1.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def compute_rotation_indicators(rotation: Rotation, schedule: tuple[ScheduledCropV2, ...], crops: dict[str, CropV2],
                                scenario: Scenario, field: FieldV2) -> tuple[dict[str, float], list[dict[str, float]]]:
    remote = {x.d: x for x in scenario.remote}
    date_set = {d.d for d in scenario.weather}
    water_results = []
    yields = []
    active_days = []
    for sc in schedule:
        crop = crops[sc.crop_id]
        wr = simulate_crop_water(crop, sc.sow_date, scenario.weather, field, remote)
        yf = yield_adjustment(crop, wr, field)
        water_results.append(wr)
        yields.append(yf)
        active_days.extend(d for d in scenario.weather if sc.sow_date <= d.d < sc.harvest_date)
    soil = soil_indicators(tuple(crops[x] for x in rotation.crop_ids), field)
    econ = rotation_economics(tuple(crops[x] for x in rotation.crop_ids), yields, field)
    irrigation = sum(w["irrigation_mm"] for w in water_results)
    yield_total = sum(y["climate_adjusted_yield_kg_ha"] for y in yields)
    etc_total = sum(w["etc_mm"] for w in water_results)
    water_stress = sum(w["water_stress_fraction"] for w in water_results) / max(1, len(water_results))
    severe = sum(w["severe_water_stress_days"] for w in water_results) / max(1, sum(crops[x].duration_days for x in rotation.crop_ids))
    heat_days = sum(w["heat_stress_days"] for w in water_results)
    heat_dd = sum(w["heat_degree_days"] for w in water_results)
    waterlog_days = sum(w["waterlogging_days"] for w in water_results)
    heavy_days = sum(w["heavy_rain_days"] for w in water_results)
    dry_days = _max_dry_days(active_days)
    taw = sum(w["taw_mm"] for w in water_results) / max(1, len(water_results))
    calendar_margins = []
    for sc in schedule:
        crop = crops[sc.crop_id]
        _, we = _window(crop.sowing_window, sc.sow_date)
        calendar_margins.append((we - sc.sow_date).days)
    calendar_margin = min(calendar_margins) if calendar_margins else 0
    labour_peak = max(crops[x].labour_person_days_ha for x in rotation.crop_ids)
    labour_total = sum(crops[x].labour_person_days_ha for x in rotation.crop_ids)
    active_remote = [remote[d.d] for d in active_days if d.d in remote]
    ndvi_vals = [x.ndvi for x in active_remote if x.ndvi is not None]
    ndmi_vals = [x.ndmi for x in active_remote if x.ndmi is not None]
    sm_vals = [x.smap_rootzone_m3_m3 for x in active_remote if x.smap_rootzone_m3_m3 is not None]
    et_vals = [x.modis_et_mm for x in active_remote if x.modis_et_mm is not None]
    values = {
        **soil,
        **econ,
        "irrigation_mm": irrigation,
        "etc_total_mm": etc_total,
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
        "flood_exposure": min(1.0, (heavy_days / max(1, sum(c.duration_days for c in [crops[x] for x in rotation.crop_ids]))) * (0.5 + 0.5 * (field.land_type.lower().find("low") >= 0))),
        "climate_adjusted_yield_kg_ha": yield_total,
        "yield_factor": sum(y["yield_factor"] for y in yields) / max(1, len(yields)),
        "scenario_yield_cv": 0.0,
        "labour_peak_person_days_ha": labour_peak,
        "calendar_margin_days": float(calendar_margin),
        "market_access_burden": max(0.0, min(1.0, 1 - field.farmer.market_access_score)),
        "rotation_length": float(len(rotation.crop_ids)),
        "mean_hls_ndvi": sum(ndvi_vals) / max(1, len(ndvi_vals)) if ndvi_vals else 0.5,
        "mean_hls_ndmi": sum(ndmi_vals) / max(1, len(ndmi_vals)) if ndmi_vals else 0.5,
        "mean_smap_rootzone_moisture": sum(sm_vals) / max(1, len(sm_vals)) if sm_vals else 0.5,
        "modis_et_mean_mm": sum(et_vals) / max(1, len(et_vals)) if et_vals else 0.0,
        "remote_observation_coverage_fraction": len(active_remote) / max(1, len(active_days)),
    }
    return values, yields


def _window(window: tuple[str, str], same: date):
    sm, sd = map(int, window[0].split("-"))
    em, ed = map(int, window[1].split("-"))
    a = date(same.year, sm, sd)
    b = date(same.year, em, ed)
    if b < a:
        b = date(same.year + 1, em, ed)
    return a, b
