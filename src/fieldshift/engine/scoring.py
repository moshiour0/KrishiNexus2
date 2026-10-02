# -*- coding: utf-8 -*-
"""
fieldshift.engine.scoring
==========================
Turns per-option, per-scenario IndicatorSets into ranked, explained
ScoredOptions (blueprint Section 6.6). Five criteria, matching the farmer
priority dimensions the app exposes (Section 8.2, screen 3):

    soil_health  <- soil_health_index
    water_saving <- irrigation_requirement_mm, water_stress_risk (avg)
    income       <- income_proxy_bdt_per_ha
    risk         <- heat_stress_days, waterlogging_risk_days,
                    turnaround_margin_days (avg)
    labour       <- labour_peak_person_days_per_ha

This mapping is a documented design choice, not a law of nature -- change it
here in one place if expert review (Section 10) says otherwise.
"""
from __future__ import annotations

import random

CRITERIA = ("soil_health", "water_saving", "income", "risk", "labour")
TURNAROUND_CAP_DAYS = 60   # clip sentinel/large turnaround values before normalizing


def _minmax_normalize(values: list, higher_is_better: bool) -> list:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    norm = [(v - lo) / (hi - lo) for v in values]
    return norm if higher_is_better else [1 - n for n in norm]


def _criterion_raw_values(indicator_sets: list) -> dict:
    """indicator_sets: list of IndicatorSet, one per option, for ONE scenario.
    Returns {criterion_name: [normalized_score_per_option]}."""
    irrigation = [ind.irrigation_requirement_mm for ind in indicator_sets]
    water_risk = [ind.water_stress_risk for ind in indicator_sets]
    soil = [ind.soil_health_index for ind in indicator_sets]
    income = [ind.income_proxy_bdt_per_ha for ind in indicator_sets]
    heat = [ind.heat_stress_days for ind in indicator_sets]
    waterlog = [ind.waterlogging_risk_days for ind in indicator_sets]
    turnaround = [min(ind.turnaround_margin_days, TURNAROUND_CAP_DAYS) for ind in indicator_sets]
    labour = [ind.labour_peak_person_days_per_ha for ind in indicator_sets]

    n_irrigation = _minmax_normalize(irrigation, higher_is_better=False)
    n_water_risk = _minmax_normalize(water_risk, higher_is_better=False)
    n_soil = _minmax_normalize(soil, higher_is_better=True)
    n_income = _minmax_normalize(income, higher_is_better=True)
    n_heat = _minmax_normalize(heat, higher_is_better=False)
    n_waterlog = _minmax_normalize(waterlog, higher_is_better=False)
    n_turnaround = _minmax_normalize(turnaround, higher_is_better=True)
    n_labour = _minmax_normalize(labour, higher_is_better=False)

    n = len(indicator_sets)
    water_saving = [(n_irrigation[i] + n_water_risk[i]) / 2 for i in range(n)]
    risk = [(n_heat[i] + n_waterlog[i] + n_turnaround[i]) / 3 for i in range(n)]

    return {
        "soil_health": n_soil,
        "water_saving": water_saving,
        "income": n_income,
        "risk": risk,
        "labour": n_labour,
    }


def criterion_scores_per_scenario(indicator_sets_by_scenario: dict) -> dict:
    """{scenario_name: {criterion: [score_per_option]}}"""
    return {s: _criterion_raw_values(sets) for s, sets in indicator_sets_by_scenario.items()}


def weighted_sum(criterion_scores_for_one_option: dict, weights: dict) -> float:
    return sum(criterion_scores_for_one_option[c] * weights.get(c, 0.0) for c in CRITERIA)


def is_pareto_optimal(index: int, criteria_matrix: list) -> bool:
    """criteria_matrix: list (per option) of dict{criterion: score}, higher=better
    for every entry (already normalized). Option `index` is Pareto-optimal if no
    other option is >= on every criterion and > on at least one."""
    me = criteria_matrix[index]
    for j, other in enumerate(criteria_matrix):
        if j == index:
            continue
        at_least_as_good = all(other[c] >= me[c] - 1e-9 for c in CRITERIA)
        strictly_better_somewhere = any(other[c] > me[c] + 1e-9 for c in CRITERIA)
        if at_least_as_good and strictly_better_somewhere:
            return False
    return True


def rank_with_robustness(option_ids: list, indicator_sets_by_scenario: dict,
                          weights: dict, n_weight_samples: int = 400,
                          seed: int = 7) -> dict:
    """
    Full Section 6.6 aggregation for one set of surviving options.

    Returns {option_id: {"mean_score", "score_by_scenario", "max_regret",
                          "pareto_optimal", "rank_probability_top1",
                          "criteria_mean"}}, plus the rank order.
    """
    scenario_names = list(indicator_sets_by_scenario.keys())
    per_scenario = criterion_scores_per_scenario(
        {s: [indicator_sets_by_scenario[s][oid] for oid in option_ids] for s in scenario_names}
    )

    score_by_scenario = {oid: {} for oid in option_ids}
    for s in scenario_names:
        for i, oid in enumerate(option_ids):
            crit = {c: per_scenario[s][c][i] for c in CRITERIA}
            score_by_scenario[oid][s] = weighted_sum(crit, weights)

    # Regret: per scenario, gap to that scenario's best option.
    max_regret = {oid: 0.0 for oid in option_ids}
    for s in scenario_names:
        best = max(score_by_scenario[oid][s] for oid in option_ids)
        for oid in option_ids:
            regret = best - score_by_scenario[oid][s]
            max_regret[oid] = max(max_regret[oid], regret)

    mean_score = {oid: sum(score_by_scenario[oid].values()) / len(scenario_names)
                  for oid in option_ids}

    # Pareto front on scenario-mean, per-criterion scores.
    criteria_mean = []
    for i, oid in enumerate(option_ids):
        criteria_mean.append({
            c: sum(per_scenario[s][c][i] for s in scenario_names) / len(scenario_names)
            for c in CRITERIA
        })
    pareto_flags = [is_pareto_optimal(i, criteria_mean) for i in range(len(option_ids))]

    # Weight-sensitivity: resample weights (Dirichlet-like via normalized
    # gamma draws) around the user's vector and tally how often each option
    # ranks first. This is what lets the product say "this ranking is
    # stable" or "this is sensitive to exactly how you weighted things."
    rng = random.Random(seed)
    top1_counts = {oid: 0 for oid in option_ids}
    concentration = 12.0   # higher = samples stay closer to the user's weights
    base = [max(weights.get(c, 0.0), 1e-6) for c in CRITERIA]
    for _ in range(n_weight_samples):
        draws = [rng.gammavariate(concentration * b, 1.0) for b in base]
        total = sum(draws)
        sampled = {c: draws[i] / total for i, c in enumerate(CRITERIA)}
        # Sensitivity pass uses the scenario-mean criteria (documented
        # simplification -- full per-scenario weight resampling is a
        # Phase-2 refinement, not needed to demonstrate the method).
        scored = {oid: weighted_sum(criteria_mean[i], sampled) for i, oid in enumerate(option_ids)}
        winner = max(scored, key=scored.get)
        top1_counts[winner] += 1

    result = {}
    for oid in option_ids:
        result[oid] = {
            "mean_score": round(mean_score[oid], 4),
            "score_by_scenario": {s: round(v, 4) for s, v in score_by_scenario[oid].items()},
            "max_regret": round(max_regret[oid], 4),
            "pareto_optimal": pareto_flags[option_ids.index(oid)],
            "rank_probability_top1": round(top1_counts[oid] / n_weight_samples, 3),
            "criteria_mean": {c: round(v, 4) for c, v in
                               criteria_mean[option_ids.index(oid)].items()},
        }
    ranked_ids = sorted(option_ids, key=lambda o: (-result[o]["mean_score"], result[o]["max_regret"]))
    return {"by_option": result, "ranked_ids": ranked_ids}
