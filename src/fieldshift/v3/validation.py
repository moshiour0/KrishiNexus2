from __future__ import annotations

from typing import Any


def structural_validation(evaluations: list, required_dimensions: tuple[str, ...], balance_tolerance_mm: float = 1e-6) -> dict[str, Any]:
    balance_errors = [abs(v.values.get("water_balance_error_mm", 0.0)) for e in evaluations for v in e.indicators_by_scenario.values()]
    checks = {
        "nonempty_evaluations": len(evaluations) > 0,
        "all_required_dimensions_present": all(set(required_dimensions).issubset(e.scenario_scores[next(iter(e.scenario_scores))].dimension_scores) for e in evaluations) if evaluations else False,
        "all_scores_finite": all(all(abs(v) < 1e9 for v in e.scenario_scores[s].dimension_scores.values()) for e in evaluations for s in e.scenario_scores),
        "uncertainty_bounds_ordered": all(e.robustness.score_p10 <= e.robustness.score_p50 <= e.robustness.score_p90 for e in evaluations),
        "regret_nonnegative": all(e.robustness.regret_max >= -1e-9 for e in evaluations),
        "water_balance_conserved": all(v <= balance_tolerance_mm for v in balance_errors),
        "rank_p90_within_rank_range": all(1.0 <= e.robustness.rank_p90 <= len(evaluations) for e in evaluations),
        "no_negative_rank": all(e.robustness.rank_mean >= 1.0 for e in evaluations),
    }
    return {"passed": all(checks.values()), "checks": checks, "max_water_balance_error_mm": max(balance_errors, default=0.0)}


def ablation_analysis(evaluations: list, weights: dict[str, float], baseline_id: str) -> dict[str, Any]:
    if not evaluations:
        return {}
    option_ids = [e.rotation.rotation_id for e in evaluations]
    scenario = next(iter(evaluations[0].scenario_scores))
    per_dim: dict[str, dict[str, float]] = {d: {} for d in weights}
    for e in evaluations:
        for d in weights:
            per_dim[d][e.rotation.rotation_id] = e.scenario_scores[scenario].dimension_scores[d]
    nominal_top = evaluations[0].rotation.rotation_id
    out = {"reference_rotation": baseline_id, "reference_rotation_present": baseline_id in option_ids, "nominal_top_rotation": nominal_top, "without_dimension": {}}
    for removed in weights:
        w = {d: v for d, v in weights.items() if d != removed}
        total = sum(w.values())
        w = {d: v / total for d, v in w.items()}
        scores = {oid: sum(per_dim[d][oid] * w[d] for d in w) for oid in option_ids}
        winner = min(option_ids, key=lambda oid: (-scores[oid], oid))
        out["without_dimension"][removed] = {"top_rotation": winner, "winner_changed_from_nominal": winner != nominal_top}
    return out
