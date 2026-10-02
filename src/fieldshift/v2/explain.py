from __future__ import annotations
from typing import Any


def explain(rotation_label: str, dimension_scores: dict[str, float], indicator_values: dict[str, float],
            baseline_values: dict[str, float] | None, scenario_scores: dict[str, float],
            dataset_registry: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_values = baseline_values or {}
    deltas = {}
    for k, v in indicator_values.items():
        if k in baseline_values and isinstance(v, (int, float)):
            deltas[k] = v - baseline_values[k]
    dims = sorted(dimension_scores.items(), key=lambda kv: kv[1], reverse=True)
    evidence = []
    for name, score in dims[:5]:
        evidence.append({"dimension": name, "normalized_score": score, "evidence_fields": _fields_for_dimension(name, indicator_values)})
    return {
        "rotation": rotation_label,
        "headline": f"{rotation_label} is evaluated from agronomic, water, climate, economic and operational evidence rather than a single proxy.",
        "top_dimensions": evidence,
        "scenario_scores": scenario_scores,
        "baseline_deltas": deltas,
        "data_lineage": [x for x in dataset_registry if x.get("status") != "unused"],
        "uncertainty_statement": "Ranking stability is estimated from priority-weight perturbations and parameter-level score perturbations; it is not a guarantee of field outcome.",
    }


def _fields_for_dimension(name: str, values: dict[str, float]) -> dict[str, float]:
    mapping = {
        "soil_health": ["soc_change_proxy_pct", "residue_score", "ground_cover_fraction", "pH_suitability"],
        "nutrient_balance": ["nitrogen_balance_proxy", "phosphorus_balance_proxy", "potassium_balance_proxy"],
        "soil_water_resilience": ["water_holding_capacity_mm", "mean_rootzone_moisture_fraction", "soil_water_deficit_mm"],
        "irrigation_demand": ["irrigation_mm", "water_productivity"],
        "drought_risk": ["water_stress_fraction", "severe_water_stress_fraction", "max_consecutive_dry_days"],
        "flood_waterlogging_risk": ["waterlogging_days", "heavy_rain_days", "flood_exposure"],
        "heat_stress_risk": ["heat_stress_days", "heat_degree_days"],
        "yield_potential": ["climate_adjusted_yield_kg_ha", "yield_factor"],
        "yield_stability": ["yield_factor", "scenario_yield_cv"],
        "economic_return": ["net_return_bdt_ha", "roi", "income_volatility_proxy"],
        "operational_feasibility": ["labour_peak_person_days_ha", "labour_total_person_days_ha", "calendar_margin_days"],
        "rotation_diversity": ["family_diversity", "disease_break_value", "legume_fraction"],
    }
    return {k: values[k] for k in mapping.get(name, []) if k in values}
