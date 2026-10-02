from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import run_v3, save_run


def main() -> int:
    parser = argparse.ArgumentParser(description="FieldShift V3 evidence-aware crop-rotation engine")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--weight-samples", type=int, default=250)
    parser.add_argument("--uncertainty-samples", type=int, default=64)
    parser.add_argument("--output", type=Path, default=Path("data/v3/fieldshift_v3_run.json"))
    args = parser.parse_args()

    run = run_v3(
        year=args.year,
        n_weight_samples=args.weight_samples,
        n_uncertainty_samples=args.uncertainty_samples,
    )
    save_run(run, args.output)
    print(f"FieldShift V3 {run.engine_version}: {len(run.evaluations)} accepted rotations; validation={run.validation['passed']}")
    for ev in run.top(5):
        r = ev.robustness
        print(f"{ev.rotation.label}: risk_adjusted={r.risk_adjusted_score:.4f}; score_p90={r.score_p90:.4f}; rank_p90={r.rank_p90:.2f}; P(top1)={r.top1_probability:.1%}")
    print(f"Saved: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
