from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from fieldshift.api.app import app


class TestProductAPI(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_product_demo_shape(self) -> None:
        r = self.client.get("/api/demo")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for key in ("run", "field", "data_quality", "strategies", "scenarios", "evidence", "explanation", "validation"):
            self.assertIn(key, data)
        self.assertGreaterEqual(len(data["strategies"]), 3)

    def test_analysis_flow_and_what_if(self) -> None:
        r = self.client.post(
            "/api/analysis/run",
            json={
                "field": {
                    "lat": 24.75,
                    "lon": 90.41,
                    "area_ha": 0.4,
                    "previous_crop": "Rice",
                    "farmer": {
                        "water_available_mm_season": 900,
                        "irrigation_reliability": 0.8,
                        "budget_bdt_ha": 100000,
                        "labour_available_person_days_ha": 120,
                    },
                },
                "priority_choices": ["water", "soil", "income"],
                "n_uncertainty_samples": 20,
                "n_weight_samples": 60,
            },
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        run_id = data["run"]["id"]
        self.assertEqual(self.client.get(f"/api/analysis/{run_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/analysis/{run_id}/strategies").status_code, 200)
        self.assertEqual(self.client.get(f"/api/analysis/{run_id}/scenarios").status_code, 200)
        self.assertEqual(self.client.get(f"/api/analysis/{run_id}/report").status_code, 200)
        if data["evidence"]["items"]:
            eid = data["evidence"]["items"][0]["id"]
            self.assertEqual(self.client.get(f"/api/analysis/{run_id}/evidence/{eid}").status_code, 200)
        what_if = self.client.post(f"/api/analysis/{run_id}/what-if", json={"scenario": "dry"})
        self.assertEqual(what_if.status_code, 200)
        self.assertIn("strategies", what_if.json())


if __name__ == "__main__":
    unittest.main()
