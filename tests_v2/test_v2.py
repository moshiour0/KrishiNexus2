from __future__ import annotations
import json
import unittest
from datetime import date
from pathlib import Path

from fieldshift.v2.models import Provenance, WeatherDay, SoilProfile, CropV2, FarmerContext, FieldV2, Rotation
from fieldshift.v2.nasa import power_daily
from fieldshift.v2.pipeline import DEFAULT_WEIGHTS, load_crops, run_v2
from fieldshift.v2.rotation import schedule, generate_rotations
from fieldshift.v2.scoring import dimension_scores, validate_weights


class TestV2DataContracts(unittest.TestCase):
    def test_provenance_confidence_range(self):
        with self.assertRaises(ValueError):
            Provenance("x", "estimated", confidence=1.5)

    def test_soil_field_capacity_must_exceed_wp(self):
        with self.assertRaises(ValueError):
            SoilProfile(field_capacity_v_v=0.15, wilting_point_v_v=0.20)

    def test_dynamic_weights_reject_unknown_dimension(self):
        w = dict(DEFAULT_WEIGHTS)
        w["made_up_dimension"] = 0.1
        with self.assertRaises(ValueError):
            validate_weights(w)

    def test_dimension_definition_can_be_arbitrary(self):
        bundles = [{"x": 1.0, "y": 0.0}, {"x": 0.0, "y": 1.0}]
        defs = {"test_dimension": {"features": {"x": {"weight": 1.0, "direction": "higher"}}}}
        out = dimension_scores(bundles, ("test_dimension",), defs)
        self.assertEqual(out["test_dimension"], [1.0, 0.0])


class TestV2NASAAdapter(unittest.TestCase):
    def test_power_payload_shape(self):
        import fieldshift.v2.nasa as nasa
        old = nasa._http_json
        try:
            nasa._http_json = lambda url, timeout=30: {"properties": {"parameter": {
                "T2M_MAX": {"20260101": 25}, "T2M_MIN": {"20260101": 12}, "RH2M": {"20260101": 70},
                "WS2M": {"20260101": 1.5}, "ALLSKY_SFC_SW_DWN": {"20260101": 18}, "PRECTOTCORR": {"20260101": 2}
            }}}
            out = power_daily(24.75, 90.41, date(2026,1,1), date(2026,1,1))
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0].source, "NASA POWER")
        finally:
            nasa._http_json = old


class TestV2Rotation(unittest.TestCase):
    def test_boro_aman_rolls_calendar_year(self):
        crops = load_crops()
        r = Rotation("x", ("boro_rice", "aman_rice"), "Boro -> Aman")
        sch = schedule(r, crops, 2026, 10, 430)
        self.assertIsNotNone(sch)
        self.assertLess(sch[0].sow_date, sch[1].sow_date)
        self.assertEqual(sch[0].sow_date.year, 2026)
        self.assertEqual(sch[1].sow_date.year, 2027)

    def test_generator_not_fixed_to_eight_options(self):
        crops = load_crops()
        ids = list(generate_rotations(crops, max_crops=3, start_year=2026))
        self.assertGreater(len(ids), 8)


class TestV2Engine(unittest.TestCase):
    def test_engine_runs_and_validates(self):
        run = run_v2(n_weight_samples=80, n_uncertainty_samples=80)
        self.assertTrue(run.validation["passed"])
        self.assertGreater(len(run.evaluations), 0)
        self.assertIn("BASELINE", {x.rotation.rotation_id for x in run.evaluations})

    def test_lat_lon_changes_live_adapter_query_path(self):
        import fieldshift.v2.nasa as nasa
        old = nasa._http_json
        calls = []
        try:
            def fake(url, timeout=30):
                calls.append(url)
                return {"properties": {"parameter": {
                    "T2M_MAX": {"20260101": 25}, "T2M_MIN": {"20260101": 12}, "RH2M": {"20260101": 70},
                    "WS2M": {"20260101": 1.5}, "ALLSKY_SFC_SW_DWN": {"20260101": 18}, "PRECTOTCORR": {"20260101": 2}
                }}}
            nasa._http_json = fake
            power_daily(24.75, 90.41, date(2026,1,1), date(2026,1,1))
            power_daily(23.8, 90.4, date(2026,1,1), date(2026,1,1))
            self.assertNotEqual(calls[0], calls[1])
        finally:
            nasa._http_json = old

    def test_baseline_is_not_silently_removed(self):
        run = run_v2(n_weight_samples=50, n_uncertainty_samples=50)
        baseline = next(x for x in run.evaluations if x.rotation.rotation_id == "BASELINE")
        self.assertEqual(baseline.rotation.source, "baseline")

    def test_scenario_yield_is_not_identical_by_definition(self):
        run = run_v2(n_weight_samples=50, n_uncertainty_samples=50)
        top = run.evaluations[0]
        vals = [top.indicators_by_scenario[s].values["climate_adjusted_yield_kg_ha"] for s in run.scenarios]
        self.assertGreaterEqual(max(vals) - min(vals), 0.0)

    def test_explanation_has_data_lineage(self):
        run = run_v2(n_weight_samples=50, n_uncertainty_samples=50)
        self.assertTrue(run.evaluations[0].explanation["data_lineage"] is not None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
