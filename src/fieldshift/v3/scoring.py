from __future__ import annotations

from collections.abc import Iterable
from statistics import mean, pstdev
from typing import Any

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
    "observation_consistency",
)


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



def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * p
    lo = int(pos)
    hi = min(len(xs) - 1, lo + 1)
    frac = pos - lo
    return xs[lo] + frac * (xs[hi] - xs[lo])

def absolute_scale(value: float, lo: float, hi: float, higher: bool) -> float:
    if hi <= lo:
        raise ValueError(f"invalid absolute scale [{lo}, {hi}]")
    x = max(lo, min(hi, float(value)))
    score = (x - lo) / (hi - lo)
    return score if higher else 1.0 - score


def _feature_score(value: float | None, spec: dict) -> float | None:
    if value is None:
        return None
    direction = spec.get("direction", "higher")
    scale = spec.get("scale")
    if not scale or len(scale) != 2:
        raise ValueError(f"V3 requires an explicit two-value scale for feature: {spec}")
    return absolute_scale(float(value), float(scale[0]), float(scale[1]), direction != "lower")


def dimension_scores(
    indicator_bundles: list[dict[str, float]],
    dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
    definitions: dict[str, dict] | None = None,
) -> dict[str, list[float]]:
    if definitions is None:
        raise ValueError("V3 scoring requires explicit config dimension definitions with absolute scales")
    outputs: dict[str, list[float]] = {}
    for dim in dimensions:
        if dim not in definitions:
            raise ValueError(f"No definition for decision dimension: {dim}")
        fmap = definitions[dim].get("features", {})
        if not fmap:
            raise ValueError(f"Decision dimension {dim} has no features")
        missing_policy = definitions[dim].get("missing_policy", "ignore")
        scores: list[float] = []
        for bundle in indicator_bundles:
            total = 0.0
            weight_total = 0.0
            for feat, raw_spec in fmap.items():
                spec = raw_spec if isinstance(raw_spec, dict) else {"weight": raw_spec}
                w = float(spec.get("weight", 0.0))
                value = bundle.get(feat)
                fs = _feature_score(value, spec)
                if fs is None:
                    if missing_policy == "neutral":
                        fs = 0.5
                    elif missing_policy == "fail":
                        raise ValueError(f"missing feature {feat!r} for dimension {dim!r}")
                    else:
                        continue
                total += w * fs
                weight_total += w
            scores.append(total / weight_total if weight_total > 0 else 0.5)
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


def rank_options(
    option_ids: list[str],
    scenario_dimension_scores: dict[str, dict[str, list[float]]],
    weights: dict[str, float],
    risk_tolerance: float = 0.5,
    n_weight_samples: int = 500,
    uncertainty_samples: dict[str, list[float]] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    dimensions = tuple(weights.keys())
    scenario_names = list(scenario_dimension_scores)
    if not option_ids:
        raise ValueError("no options to rank")

    scenario_scores: dict[str, dict[str, float]] = {oid: {} for oid in option_ids}
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

    # Priority-weight sensitivity: Dirichlet-like gamma sampling centred on declared priorities.
    import random
    rng = random.Random(seed)
    top_counts = {o: 0 for o in option_ids}
    sensitivity_ranks: dict[str, list[int]] = {o: [] for o in option_ids}
    base = [max(weights[d], 1e-4) for d in dimensions]
    for _ in range(n_weight_samples):
        draws = [rng.gammavariate(20 * b, 1.0) for b in base]
        total = sum(draws)
        sampled = {d: draws[i] / total for i, d in enumerate(dimensions)}
        vals = {o: sum(scenario_dims_mean[o][d] * sampled[d] for d in dimensions) for o in option_ids}
        ordered = sorted(option_ids, key=lambda o: vals[o], reverse=True)
        top_counts[ordered[0]] += 1
        for r, oid in enumerate(ordered, 1):
            sensitivity_ranks[oid].append(r)

    score_samples = uncertainty_samples or {
        o: [mean_score[o]] for o in option_ids
    }
    result: dict[str, dict] = {}
    for i, oid in enumerate(option_ids):
        u = sorted(score_samples[oid])
        score_std = pstdev(u) if len(u) > 1 else 0.0
        risk_adjusted = mean_score[oid] - (1.0 - risk_tolerance) * score_std
        result[oid] = {
            "scenario_scores": scenario_scores[oid],
            "dimension_scores": scenario_dims_mean[oid],
            "mean_score": mean_score[oid],
            "max_regret": regret[oid],
            "pareto_optimal": pareto[i],
            "top1_probability": top_counts[oid] / max(1, n_weight_samples),
            "rank_mean": mean(sensitivity_ranks[oid]),
            "rank_p90": percentile([float(x) for x in sensitivity_ranks[oid]], 0.90),
            "score_p10": percentile(u, 0.10),
            "score_p50": percentile(u, 0.50),
            "score_p90": percentile(u, 0.90),
            "score_std": score_std,
            "risk_adjusted_score": risk_adjusted,
        }
    ordered = sorted(
        option_ids,
        key=lambda o: (-result[o]["risk_adjusted_score"], result[o]["max_regret"], result[o]["rank_mean"], o),
    )
    return {"results": result, "ranked_ids": ordered}
