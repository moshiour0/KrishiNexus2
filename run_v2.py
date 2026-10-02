from __future__ import annotations
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fieldshift.v2.pipeline import run_v2, save_run

ROOT = Path(__file__).resolve().parent


def main() -> None:
    run = run_v2()
    out = ROOT / "data" / "v2" / "fieldshift_v2_run.json"
    save_run(run, out)
    report = ROOT / "docs" / "v2" / "judge_report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Field Shift V2 — decision-support engine evidence report",
        "",
        f"Engine version: `{run.engine_version}`",
        f"Field: `{run.field_id}`",
        "",
        "## Ranked rotation set",
        "",
        "| Rank | Rotation | Mean score | Top-1 probability | P10 | P50 | P90 | Max regret | Pareto |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for i, e in enumerate(run.evaluations, 1):
        r = e.robustness
        lines.append(f"| {i} | {e.rotation.label} | {r.score_mean:.3f} | {r.top1_probability:.2f} | {r.score_p10:.3f} | {r.score_p50:.3f} | {r.score_p90:.3f} | {r.regret_max:.3f} | {'yes' if r.pareto_optimal else 'no'} |")
    lines += ["", "## Data registry", "", "| Dataset | Type | Status | Confidence |", "|---|---|---|---:|"]
    for d in run.dataset_registry:
        lines.append(f"| {d.get('name')} | {d.get('source_type','')} | {d.get('status','')} | {d.get('confidence','')} |")
    lines += [
        "", "## Validation", "", f"Structural validation passed: **{run.validation.get('passed')}**", "",
        "```json", json.dumps(run.ablation, indent=2), "```", "",
        "## What the engine can demonstrate to a judge", "",
        "1. NASA-compatible field-location weather ingestion is implemented through the NASA POWER Daily API adapter.",
        "2. Additional NASA product adapters accept GPM IMERG, SMAP, HLS and MODIS-derived time-series data without changing the decision engine.",
        "3. Climate scenarios can be supplied from NASA NEX-GDDP-CMIP6 files; when not present, the demo uses clearly labelled diagnostic scenarios rather than pretending they are NASA projections.",
        "4. Rotation generation is constraint-driven rather than a fixed eight-option YAML list.",
        "5. Water is simulated with root-zone storage, crop root depth, rainfall infiltration/runoff and rice standing-water terms.",
        "6. Yield changes with water/heat/flood/salinity stress before economics are calculated.",
        "7. The decision layer is configurable: decision dimensions and their feature definitions are data/config driven, not a hard-coded five-criterion scorer.",
        "8. The engine reports scenario scores, Pareto membership, regret, priority sensitivity and an uncertainty envelope instead of hiding uncertainty behind one number.",
        "9. Every dataset can carry provenance and confidence metadata, so observed, satellite-derived, modelled, estimated and synthetic values remain distinguishable.",
        "",
        "## Current demo data state",
        "",
        "The engine is fully runnable before BAU data arrives. The current demo field/crop economics are labelled defaults; replacing them with BAU/BRRI/BARI/local observations changes the evidence layer, not the engine architecture.",
        "",
        "## NASA judge framing",
        "",
        "- **Impact:** farm-scale rotation planning joins water, soil, climate, yield and economics in one scenario engine.",
        "- **Creativity:** Earth observation is not just visualized; it is converted into state variables that affect crop water balance, stress, yield and the decision frontier.",
        "- **Validity:** formulas, assumptions, provenance, validation tests, ablations and uncertainty outputs are first-class engine objects.",
        "- **Relevance:** the system directly addresses rotation strategies, soil health, water conservation and climate adaptation using NASA-compatible data paths.",
        "- **Presentation:** the output is an explainable evidence chain rather than an unexplained recommendation.",
        "",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Wrote {report}")


if __name__ == "__main__":
    main()
