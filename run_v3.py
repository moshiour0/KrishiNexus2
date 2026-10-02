from __future__ import annotations

import argparse
from pathlib import Path

from fieldshift.v3.pipeline import run_v3, save_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FieldShift V3")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--uncertainty-samples", type=int, default=64)
    parser.add_argument("--weight-samples", type=int, default=250)
    parser.add_argument("--output", type=Path, default=Path("data/v3/fieldshift_v3_run.json"))
    args = parser.parse_args()
    run = run_v3(year=args.year, n_uncertainty_samples=args.uncertainty_samples, n_weight_samples=args.weight_samples)
    save_run(run, args.output)
    print(f"FieldShift V3 {run.engine_version}")
    print(f"evaluations={len(run.evaluations)} validation={'PASS' if run.validation['passed'] else 'CHECK'}")
    for idx, e in enumerate(run.evaluations[:5], 1):
        print(f"{idx}. {e.rotation.label} | risk_adjusted={e.robustness.risk_adjusted_score:.4f} | p(top1)={e.robustness.top1_probability:.1%}")
    print(f"saved={args.output}")


if __name__ == "__main__":
    main()
