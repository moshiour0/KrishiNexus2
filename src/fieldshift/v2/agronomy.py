from __future__ import annotations

from dataclasses import dataclass
from .models import CropV2, FieldV2, ScheduledCropV2


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def soil_water_capacity(field: FieldV2, root_depth_m: float) -> float:
    soil = field.soil
    if soil.field_capacity_v_v is not None and soil.wilting_point_v_v is not None:
        aw = soil.field_capacity_v_v - soil.wilting_point_v_v
    else:
        clay = soil.clay_pct or 25
        sand = soil.sand_pct or 35
        if clay > 35: aw = 0.18
        elif sand > 65: aw = 0.10
        else: aw = 0.14
    depth = min(root_depth_m, soil.soil_depth_m or root_depth_m)
    return aw * depth * 1000


def yield_adjustment(crop: CropV2, water: dict[str, float], field: FieldV2) -> dict[str, float]:
    water_penalty = _clamp(water["water_stress_fraction"] * crop.yield_stress_sens_water)
    heat_window_penalty = _clamp((water["heat_degree_days"] / max(1.0, crop.duration_days * 3.0)) * crop.yield_stress_sens_heat)
    flood_penalty = _clamp(water["waterlogging_days"] / max(1, crop.duration_days) * (1 - crop.waterlogging_tolerance))
    salinity = (field.soil.ec_ds_m or 0.0)
    salinity_penalty = _clamp(max(0.0, salinity - 2.0) / 8.0 * (1 - crop.salinity_tolerance))
    total = _clamp(1 - (0.55 * water_penalty + 0.25 * heat_window_penalty + 0.12 * flood_penalty + 0.08 * salinity_penalty))
    return {
        "water_penalty": water_penalty,
        "heat_penalty": heat_window_penalty,
        "flood_penalty": flood_penalty,
        "salinity_penalty": salinity_penalty,
        "yield_factor": total,
        "climate_adjusted_yield_kg_ha": crop.yield_kg_ha * total,
    }


def soil_indicators(rotation: tuple[CropV2, ...], field: FieldV2) -> dict[str, float]:
    soil = field.soil
    n_fix = sum(1 for c in rotation if c.n_fixing) / max(1, len(rotation))
    residue = sum(c.residue_score for c in rotation) / max(1, len(rotation))
    family_div = len({c.family for c in rotation}) / max(1, len(rotation))
    cover = min(1.0, sum(c.duration_days for c in rotation) / 365)
    ph_center = (soil.ph if soil.ph is not None else 6.5)
    ph_suitable = sum(1 for c in rotation if c.pH_range[0] <= ph_center <= c.pH_range[1]) / max(1, len(rotation))
    n_demand = sum(c.n_demand_kg_ha for c in rotation)
    n_supply_proxy = (soil.total_n_mgkg or 0.0) * 0.01
    n_balance = n_supply_proxy + 15 * sum(c.n_fixing for c in rotation) - n_demand
    p_balance = (soil.available_p_mgkg or 0.0) - sum(c.p_demand_kg_ha for c in rotation) * 0.1
    k_balance = (soil.exchangeable_k_mgkg or 0.0) - sum(c.k_demand_kg_ha for c in rotation) * 0.1
    soc_delta = 0.08 * n_fix + 0.04 * residue + 0.03 * cover - 0.02 * (1 - cover)
    return {
        "soc_baseline_pct": soil.soc_pct if soil.soc_pct is not None else 0.0,
        "soc_change_proxy_pct": soc_delta,
        "nitrogen_balance_proxy": n_balance,
        "phosphorus_balance_proxy": p_balance,
        "potassium_balance_proxy": k_balance,
        "pH_suitability": ph_suitable,
        "salinity_risk": _clamp(max(0.0, (soil.ec_ds_m or 0.0) - 2.0) / 8.0),
        "water_holding_capacity_mm": sum(soil_water_capacity(field, c.root_depth_m) for c in rotation) / max(1, len(rotation)),
        "legume_fraction": n_fix,
        "residue_score": residue,
        "family_diversity": family_div,
        "ground_cover_fraction": cover,
        "disease_break_value": sum(c.family_break_value for c in rotation) / max(1, len(rotation)),
    }
