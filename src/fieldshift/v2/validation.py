from __future__ import annotations
from typing import Any


def structural_validation(evaluations: list, required_dimensions: tuple[str, ...]) -> dict[str, Any]:
    checks = {
        "nonempty_evaluations": len(evaluations) > 0,
        "all_required_dimensions_present": all(set(required_dimensions).issubset(e.scenario_scores[next(iter(e.scenario_scores))].dimension_scores) for e in evaluations) if evaluations else False,
        "all_scores_finite": all(all(abs(v) < 1e9 for v in e.scenario_scores[s].dimension_scores.values()) for e in evaluations for s in e.scenario_scores),
        "uncertainty_bounds_ordered": all(e.robustness.score_p10 <= e.robustness.score_p50 <= e.robustness.score_p90 for e in evaluations),
        "regret_nonnegative": all(e.robustness.regret_max >= -1e-9 for e in evaluations),
    }
    return {"passed": all(checks.values()), "checks": checks}


def ablation_analysis(evaluations: list, weights: dict[str, float], baseline_id: str) -> dict[str, Any]:
    if not evaluations:
        return {}
    option_ids = [e.rotation.rotation_id for e in evaluations]
    # Use each option's baseline scenario dimension scores as an interpretable ablation matrix.
    scenario = next(iter(evaluations[0].scenario_scores))
    per_dim = {d: {} for d in weights}
    for e in evaluations:
        for d in weights:
            per_dim[d][e.rotation.rotation_id] = e.scenario_scores[scenario].dimension_scores[d]
    baseline = baseline_id
    nominal_top = evaluations[0].rotation.rotation_id
    out = {"reference_rotation": baseline, "reference_rotation_present": baseline in option_ids, "nominal_top_rotation": nominal_top, "without_dimension": {}}
    for removed in weights:
        w = {d: v for d, v in weights.items() if d != removed}
        total = sum(w.values())
        w = {d: v / total for d, v in w.items()}
        scores = []
        for oid in option_ids:
            x = sum(per_dim[d][oid] * w[d] for d in w)
            scores.append((x, oid))
        winner = max(scores)[1]
        out["without_dimension"][removed] = {"top_rotation": winner, "winner_changed_from_nominal": winner != nominal_top, "winner_changed_from_baseline": winner != baseline}
    return out
