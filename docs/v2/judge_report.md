# Field Shift V2 — decision-support engine evidence report

Engine version: `2.0.0`
Field: `mymensingh_demo_v2`

## Ranked rotation set

| Rank | Rotation | Mean score | Top-1 probability | P10 | P50 | P90 | Max regret | Pareto |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | Boro rice -> Lentil | 0.566 | 0.26 | 0.545 | 0.564 | 0.583 | 0.000 | yes |
| 2 | Wheat -> Mustard | 0.562 | 0.07 | 0.541 | 0.562 | 0.583 | 0.004 | yes |
| 3 | Wheat | 0.550 | 0.17 | 0.532 | 0.552 | 0.569 | 0.017 | yes |
| 4 | Wheat -> Jute -> Mustard | 0.545 | 0.08 | 0.525 | 0.547 | 0.567 | 0.022 | yes |
| 5 | Lentil | 0.544 | 0.26 | 0.524 | 0.545 | 0.569 | 0.023 | yes |
| 6 | Wheat -> Jute | 0.525 | 0.00 | 0.502 | 0.526 | 0.543 | 0.042 | yes |
| 7 | Jute -> Wheat | 0.516 | 0.00 | 0.496 | 0.517 | 0.539 | 0.051 | no |
| 8 | Wheat -> Jute -> Aman rice | 0.510 | 0.07 | 0.494 | 0.514 | 0.535 | 0.058 | yes |
| 9 | Boro rice -> Mustard | 0.510 | 0.00 | 0.490 | 0.509 | 0.530 | 0.057 | yes |
| 10 | Lentil -> Jute | 0.505 | 0.00 | 0.485 | 0.505 | 0.526 | 0.062 | yes |
| 11 | Lentil -> Aman rice | 0.502 | 0.00 | 0.482 | 0.503 | 0.522 | 0.068 | yes |
| 12 | Lentil -> Jute -> Aman rice | 0.501 | 0.03 | 0.479 | 0.503 | 0.522 | 0.068 | yes |
| 13 | Jute -> Lentil | 0.497 | 0.00 | 0.475 | 0.497 | 0.517 | 0.070 | no |
| 14 | Jute | 0.497 | 0.00 | 0.479 | 0.497 | 0.517 | 0.070 | yes |
| 15 | Aman rice | 0.490 | 0.04 | 0.471 | 0.492 | 0.510 | 0.077 | yes |
| 16 | Jute -> Boro rice | 0.486 | 0.00 | 0.469 | 0.488 | 0.510 | 0.081 | yes |
| 17 | Jute -> Aman rice | 0.482 | 0.00 | 0.459 | 0.481 | 0.500 | 0.084 | yes |
| 18 | Aman rice -> Jute | 0.480 | 0.00 | 0.461 | 0.481 | 0.502 | 0.087 | yes |
| 19 | Boro rice | 0.477 | 0.00 | 0.454 | 0.476 | 0.496 | 0.090 | yes |
| 20 | Current/baseline practice | 0.472 | 0.01 | 0.449 | 0.470 | 0.489 | 0.096 | yes |
| 21 | Mustard -> Jute -> Aman rice | 0.453 | 0.00 | 0.431 | 0.455 | 0.476 | 0.114 | yes |
| 22 | Mustard -> Jute | 0.441 | 0.00 | 0.419 | 0.441 | 0.464 | 0.125 | yes |
| 23 | Mustard -> Aman rice | 0.440 | 0.00 | 0.418 | 0.440 | 0.465 | 0.129 | yes |
| 24 | Jute -> Mustard | 0.434 | 0.00 | 0.409 | 0.432 | 0.455 | 0.133 | no |
| 25 | Mustard | 0.426 | 0.00 | 0.407 | 0.431 | 0.450 | 0.140 | yes |

## Data registry

| Dataset | Type | Status | Confidence |
|---|---|---|---:|
| NASA POWER |  | unavailable |  |
| Synthetic fallback weather | synthetic | fallback | 0.25 |
| Diagnostic scenario ssp245 | estimated | fallback | 0.35 |
| Diagnostic scenario ssp585 | estimated | fallback | 0.35 |

## Validation

Structural validation passed: **True**

```json
{
  "reference_rotation": "BASELINE",
  "reference_rotation_present": true,
  "nominal_top_rotation": "GEN-000014",
  "without_dimension": {
    "soil_health": {
      "top_rotation": "GEN-000071",
      "winner_changed_from_nominal": true,
      "winner_changed_from_baseline": true
    },
    "nutrient_balance": {
      "top_rotation": "GEN-000069",
      "winner_changed_from_nominal": true,
      "winner_changed_from_baseline": true
    },
    "soil_water_resilience": {
      "top_rotation": "GEN-000014",
      "winner_changed_from_nominal": false,
      "winner_changed_from_baseline": true
    },
    "irrigation_demand": {
      "top_rotation": "GEN-000014",
      "winner_changed_from_nominal": false,
      "winner_changed_from_baseline": true
    },
    "drought_risk": {
      "top_rotation": "GEN-000071",
      "winner_changed_from_nominal": true,
      "winner_changed_from_baseline": true
    },
    "flood_waterlogging_risk": {
      "top_rotation": "GEN-000108",
      "winner_changed_from_nominal": true,
      "winner_changed_from_baseline": true
    },
    "heat_stress_risk": {
      "top_rotation": "GEN-000014",
      "winner_changed_from_nominal": false,
      "winner_changed_from_baseline": true
    },
    "yield_potential": {
      "top_rotation": "GEN-000108",
      "winner_changed_from_nominal": true,
      "winner_changed_from_baseline": true
    },
    "yield_stability": {
      "top_rotation": "GEN-000108",
      "winner_changed_from_nominal": true,
      "winner_changed_from_baseline": true
    },
    "economic_return": {
      "top_rotation": "GEN-000064",
      "winner_changed_from_nominal": true,
      "winner_changed_from_baseline": true
    },
    "operational_feasibility": {
      "top_rotation": "GEN-000014",
      "winner_changed_from_nominal": false,
      "winner_changed_from_baseline": true
    },
    "rotation_diversity": {
      "top_rotation": "GEN-000071",
      "winner_changed_from_nominal": true,
      "winner_changed_from_baseline": true
    }
  }
}
```

## What the engine can demonstrate to a judge

1. NASA-compatible field-location weather ingestion is implemented through the NASA POWER Daily API adapter.
2. Additional NASA product adapters accept GPM IMERG, SMAP, HLS and MODIS-derived time-series data without changing the decision engine.
3. Climate scenarios can be supplied from NASA NEX-GDDP-CMIP6 files; when not present, the demo uses clearly labelled diagnostic scenarios rather than pretending they are NASA projections.
4. Rotation generation is constraint-driven rather than a fixed eight-option YAML list.
5. Water is simulated with root-zone storage, crop root depth, rainfall infiltration/runoff and rice standing-water terms.
6. Yield changes with water/heat/flood/salinity stress before economics are calculated.
7. The decision layer is configurable: decision dimensions and their feature definitions are data/config driven, not a hard-coded five-criterion scorer.
8. The engine reports scenario scores, Pareto membership, regret, priority sensitivity and an uncertainty envelope instead of hiding uncertainty behind one number.
9. Every dataset can carry provenance and confidence metadata, so observed, satellite-derived, modelled, estimated and synthetic values remain distinguishable.

## Current demo data state

The engine is fully runnable before BAU data arrives. The current demo field/crop economics are labelled defaults; replacing them with BAU/BRRI/BARI/local observations changes the evidence layer, not the engine architecture.

## NASA judge framing

- **Impact:** farm-scale rotation planning joins water, soil, climate, yield and economics in one scenario engine.
- **Creativity:** Earth observation is not just visualized; it is converted into state variables that affect crop water balance, stress, yield and the decision frontier.
- **Validity:** formulas, assumptions, provenance, validation tests, ablations and uncertainty outputs are first-class engine objects.
- **Relevance:** the system directly addresses rotation strategies, soil health, water conservation and climate adaptation using NASA-compatible data paths.
- **Presentation:** the output is an explainable evidence chain rather than an unexplained recommendation.
