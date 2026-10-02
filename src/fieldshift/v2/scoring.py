from __future__ import annotations

import random
from statistics import mean, quantiles
from typing import Iterable

DEFAULT_DIMENSIONS = (
    "soil_health",
    "nutrient_balance",
    "soil_water_resilience",
    "irrigation_demand",
    "drought_risk",
    "flood_waterlogging_risk",
    "heat_stress_risk",
    "yield_potential",
    "yield_stability",
    "economic_return",
    "operational_feasibility",
    "rotation_diversity",
)

DIMENSION_FEATURES = {
    "soil_health": {"soc_change_proxy_pct": 0.25, "residue_score": 0.25, "ground_cover_fraction": 0.20, "disease_break_value": 0.10, "pH_suitability": 0.20},
    "nutrient_balance": {"nitrogen_balance_proxy": 0.40, "phosphorus_balance_proxy": 0.20, "potassium_balance_proxy": 0.20, "legume_fraction": 0.20},
    "soil_water_resilience": {"water_holding_capacity_mm": 0.55, "mean_rootzone_moisture_fraction": 0.30, "soil_water_deficit_mm": 0.15},
    "irrigation_demand": {"irrigation_mm": 0.65, "irrigation_reliability_burden": 0.20, "water_productivity": 0.15},
    "drought_risk": {"water_stress_fraction": 0.50, "severe_water_stress_fraction": 0.25, "max_consecutive_dry_days": 0.25},
    "flood_waterlogging_risk": {"waterlogging_days": 0.45, "heavy_rain_days": 0.20, "flood_exposure": 0.35},
    "heat_stress_risk": {"heat_stress_days": 0.55, "heat_degree_days": 0.45},
    "yield_potential": {"climate_adjusted_yield_kg_ha": 0.70, "yield_factor": 0.30},
    "yield_stability": {"yield_factor": 0.55, "scenario_yield_cv": 0.45},
    "economic_return": {"net_return_bdt_ha": 0.65, "roi": 0.20, "income_volatility_proxy": 0.15},
    "operational_feasibility": {"labour_peak_person_days_ha": 0.45, "labour_total_person_days_ha": 0.25, "calendar_margin_days": 0.20, "market_access_burden": 0.10},
    "rotation_diversity": {"family_diversity": 0.45, "disease_break_value": 0.35, "legume_fraction": 0.20},
}


def minmax(values: list[float], higher: bool) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    out = [(v - lo) / (hi - lo) for v in values]
    return out if higher else [1 - x for x in out]


def validate_weights(weights: dict[str, float], dimensions: Iterable[str] = DEFAULT_DIMENSIONS) -> None:
    dims = tuple(dimensions)
    unknown = set(weights) - set(dims)
    missing = set(dims) - set(weights)
    if unknown:
        raise ValueError(f"unknown decision dimensions: {sorted(unknown)}")
    if missing:
        raise ValueError(f"missing decision dimensions: {sorted(missing)}")
    if any(v < 0 for v in weights.values()):
        raise ValueError("weights must be non-negative")
    if abs(sum(weights.values()) - 1.0) > 1e-6:
        raise ValueError("weights must sum to 1")


def _feature_matrix(indicator_bundles: list[dict[str, float]], feature: str, higher: bool) -> list[float]:
    vals = [float(b.get(feature, 0.0)) for b in indicator_bundles]
    return minmax(vals, higher)


def dimension_scores(indicator_bundles: list[dict[str, float]], dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
                     definitions: dict[str, dict] | None = None) -> dict[str, list[float]]:
    if definitions is None:
        lower_features = {
            "irrigation_mm", "irrigation_reliability_burden", "water_stress_fraction",
            "severe_water_stress_fraction", "max_consecutive_dry_days", "waterlogging_days",
            "heavy_rain_days", "flood_exposure", "heat_stress_days", "heat_degree_days",
            "scenario_yield_cv", "income_volatility_proxy", "labour_peak_person_days_ha",
            "labour_total_person_days_ha", "market_access_burden", "soil_water_deficit_mm"
        }
        definitions = {}
        for d, fmap in DIMENSION_FEATURES.items():
            definitions[d] = {"features": {
                f: {"weight": w, "direction": "lower" if f in lower_features else "higher"}
                for f, w in fmap.items()
            }}
    outputs = {}
    for dim in dimensions:
        if dim not in definitions:
            raise ValueError(f"No definition for decision dimension: {dim}")
        fmap = definitions[dim].get("features", {})
        if not fmap:
            raise ValueError(f"Decision dimension {dim} has no features")
        norm_by_feature = {}
        for feat, spec in fmap.items():
            direction = spec.get("direction", "higher") if isinstance(spec, dict) else "higher"
            norm_by_feature[feat] = _feature_matrix(indicator_bundles, feat, direction != "lower")
        total_w = sum(float(spec.get("weight", 0.0) if isinstance(spec, dict) else spec) for spec in fmap.values())
        if total_w <= 0:
            raise ValueError(f"Decision dimension {dim} has zero feature weight")
        scores = []
        for i in range(len(indicator_bundles)):
            score = 0.0
            for feat, spec in fmap.items():
                w = float(spec.get("weight", 0.0) if isinstance(spec, dict) else spec)
                score += norm_by_feature[feat][i] * w
            scores.append(score / total_w)
        outputs[dim] = scores
    return outputs


def pareto_flags(matrix: list[dict[str, float]], dimensions: tuple[str, ...]) -> list[bool]:
    flags = []
    for i, me in enumerate(matrix):
        optimal = True
        for j, other in enumerate(matrix):
            if i == j:
                continue
            ge = all(other[d] >= me[d] - 1e-12 for d in dimensions)
            gt = any(other[d] > me[d] + 1e-12 for d in dimensions)
            if ge and gt:
                optimal = False
                break
        flags.append(optimal)
    return flags


def rank_options(option_ids: list[str], scenario_dimension_scores: dict[str, dict[str, list[float]]], weights: dict[str, float],
                 n_weight_samples: int = 500, n_uncertainty_samples: int = 300, seed: int = 42) -> dict[str, dict]:
    dimensions = tuple(weights.keys())
    scenario_names = list(scenario_dimension_scores)
    n = len(option_ids)
    scenario_scores = {oid: {} for oid in option_ids}
    scenario_dims_mean = {oid: {d: 0.0 for d in dimensions} for oid in option_ids}
    for s in scenario_names:
        ds = scenario_dimension_scores[s]
        for i, oid in enumerate(option_ids):
            for d in dimensions:
                scenario_dims_mean[oid][d] += ds[d][i] / len(scenario_names)
            scenario_scores[oid][s] = sum(ds[d][i] * weights[d] for d in dimensions)
    pareto = pareto_flags([scenario_dims_mean[oid] for oid in option_ids], dimensions)
    best_by_s = {s: max(scenario_scores[o][s] for o in option_ids) for s in scenario_names}
    regret = {o: max(best_by_s[s] - scenario_scores[o][s] for s in scenario_names) for o in option_ids}
    mean_score = {o: mean(scenario_scores[o].values()) for o in option_ids}

    rng = random.Random(seed)
    top_counts = {o: 0 for o in option_ids}
    rank_samples = {o: [] for o in option_ids}
    base = [max(weights[d], 1e-6) for d in dimensions]
    for _ in range(n_weight_samples):
        draws = [rng.gammavariate(10 * b, 1) for b in base]
        total = sum(draws)
        sampled = {d: draws[i] / total for i, d in enumerate(dimensions)}
        vals = {o: sum(scenario_dims_mean[o][d] * sampled[d] for d in dimensions) for o in option_ids}
        ordered = sorted(option_ids, key=lambda o: vals[o], reverse=True)
        top_counts[ordered[0]] += 1
        for r, oid in enumerate(ordered, 1):
            rank_samples[oid].append(r)

    # A second uncertainty layer perturbs the scenario-mean dimension scores. This
    # is a dimension-level proxy when the full parameter Monte Carlo is supplied by pipeline.
    uncertainty_scores = {o: [] for o in option_ids}
    for _ in range(n_uncertainty_samples):
        vals = {}
        for o in option_ids:
            jittered = []
            for d in dimensions:
                v = scenario_dims_mean[o][d]
                jittered.append((d, max(0.0, min(1.0, rng.gauss(v, 0.035 + 0.04 * (1 - v))))))
            vals[o] = sum(x * weights[d] for d, x in jittered)
        for o in option_ids:
            uncertainty_scores[o].append(vals[o])

    result = {}
    for i, oid in enumerate(option_ids):
        u = sorted(uncertainty_scores[oid])
        q = quantiles(u, n=10) if len(u) >= 10 else [u[0]] * 9
        result[oid] = {
            "scenario_scores": scenario_scores[oid],
            "dimension_scores": scenario_dims_mean[oid],
            "mean_score": mean_score[oid],
            "max_regret": regret[oid],
            "pareto_optimal": pareto[i],
            "top1_probability": top_counts[oid] / max(1, n_weight_samples),
            "rank_mean": mean(rank_samples[oid]),
            "rank_p90": q[8] if len(q) >= 9 else q[-1],
            "score_p10": q[0],
            "score_p50": u[len(u)//2],
            "score_p90": q[8] if len(q) >= 9 else q[-1],
        }
    ordered = sorted(option_ids, key=lambda o: (-result[o]["mean_score"], result[o]["max_regret"], result[o]["rank_mean"]))
    return {"results": result, "ranked_ids": ordered}
