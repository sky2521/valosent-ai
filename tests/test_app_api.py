import io
import unittest
from unittest.mock import patch

from app import app


class SentimentApiValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health_route(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_malformed_payload_returns_json_error(self):
        response = self.client.post("/api/sentiment/analyze", data="{bad", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_non_text_review_is_rejected(self):
        response = self.client.post("/api/sentiment/analyze", json={"review": ["not", "text"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("text", response.get_json()["error"])

    def test_empty_review_is_rejected_before_model_loading(self):
        with patch("app.load_assets") as load_assets:
            response = self.client.post("/api/sentiment/analyze", json={"review": "   "})
        self.assertEqual(response.status_code, 400)
        load_assets.assert_not_called()

    def test_overlong_review_is_rejected_before_model_loading(self):
        with patch("app.load_assets") as load_assets:
            response = self.client.post("/api/sentiment/analyze", json={"review": "a" * 5001})
        self.assertEqual(response.status_code, 400)
        load_assets.assert_not_called()

    def test_agent_map_filters_compose_before_side_ranking(self):
        rows = [
            {"agent_name": "Jett", "role": "Duelist", "appearances": 20,
             "attack_acs_median": 220.0, "defense_acs_median": 180.0},
            {"agent_name": "Sage", "role": "Sentinel", "appearances": 25,
             "attack_acs_median": 170.0, "defense_acs_median": 190.0},
        ]
        with patch("app.get_maps", return_value=["Ascent"]), patch(
            "app.get_agents", return_value=[{"agent": "Jett"}, {"agent": "Sage"}]
        ), patch("app.get_map_agent_stats", return_value=rows) as get_stats:
            response = self.client.get(
                "/api/agent-map-performance?map=ascent&agent=jett&role=Duelist&side=attack"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["map"], "Ascent")
        self.assertEqual(payload["agent"], "Jett")
        self.assertEqual(payload["role"], "Duelist")
        self.assertEqual(payload["side"], "attack")
        self.assertEqual(payload["ranking_metric"], "median T-side ACS")
        self.assertEqual([row["agent_name"] for row in payload["stats"]], ["Jett"])
        get_stats.assert_called_once_with("Ascent", "Duelist")

    def test_sentiment_analyze_returns_probabilities_and_xai_explanation(self):
        response = self.client.post(
            "/api/sentiment/analyze",
            json={"review": "Jett is amazing and super fun on Ascent, but matchmaking is terrible."},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("ensemble", payload)
        self.assertIn("probabilities", payload["ensemble"])
        self.assertIn("explanation", payload)
        self.assertTrue(payload["explanation"]["available"])
        self.assertIn("positive_terms", payload["explanation"])
        self.assertIn("negative_terms", payload["explanation"])

    def test_sentiment_batch_json_and_csv_upload(self):
        json_res = self.client.post(
            "/api/sentiment/batch",
            json={
                "reviews": [
                    "Amazing tactical shooter with smooth FPS!",
                    "Terrible matchmaking and awful anti-cheat crashes.",
                ],
                "include_distilbert": False,
            },
        )
        self.assertEqual(json_res.status_code, 200)
        data = json_res.get_json()
        self.assertEqual(data["processed_count"], 2)
        self.assertEqual(len(data["items"]), 2)

        csv_bytes = b"review_text\nGreat gunplay and fun abilities.\nLaggy servers and toxic players.\n"
        csv_res = self.client.post(
            "/api/sentiment/batch",
            data={"file": (io.BytesIO(csv_bytes), "sample.csv"), "include_distilbert": "false"},
            content_type="multipart/form-data",
        )
        self.assertEqual(csv_res.status_code, 200)
        self.assertEqual(csv_res.get_json()["processed_count"], 2)

    def test_match_draft_predict_endpoint_and_validation(self):
        res = self.client.post(
            "/api/match/predict",
            json={
                "map": "Ascent",
                "team1": ["Jett", "KAY/O", "Killjoy", "Omen", "Sova"],
                "team2": ["Astra", "Breach", "Chamber", "Raze", "Skye"],
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["map"], "Ascent")
        self.assertIsNotNone(data["ml_prediction"])
        total_prob = data["ml_prediction"]["team1_win_probability"] + data["ml_prediction"]["team2_win_probability"]
        self.assertAlmostEqual(total_prob, 1.0, delta=0.01)

        bad_res = self.client.post(
            "/api/match/predict",
            json={
                "map": "Ascent",
                "team1": ["Jett", "Jett", "Killjoy", "Omen", "Sova"],
                "team2": ["Astra", "Breach", "Chamber", "Raze", "Skye"],
            },
        )
        self.assertEqual(bad_res.status_code, 400)

    def test_2026_roster_profiles_compare_and_route_aliases(self):
        for route in ("/overview", "/maps", "/agents", "/recommendations", "/compare", "/sentiment", "/model-lab"):
            self.assertEqual(self.client.get(route).status_code, 200, f"Route failed: {route}")

        modern_agents = ("Clove", "Vyse", "Tejo", "Waylay", "Veto", "Miks", "Hush", "Yoru", "Gekko", "Deadlock", "Iso")
        for agent in modern_agents:
            res = self.client.get(f"/api/agents/{agent}")
            self.assertEqual(res.status_code, 200, f"Agent failed: {agent}")
            data = res.get_json()
            self.assertTrue(data["has_match_data"])
            self.assertGreater(data["historical"]["overall"]["appearances"], 0)
            self.assertTrue(data["best_maps"])
            self.assertTrue(data["worst_maps"])
            self.assertGreater(data["review_sentiment"]["total_mentions"], 0)

        for a, b in (("Veto", "Vyse"), ("Yoru", "Waylay"), ("Miks", "Clove"), ("Gekko", "Tejo")):
            cmp_res = self.client.get(f"/api/agent-comparison?agent={a}&agent={b}")
            self.assertEqual(cmp_res.status_code, 200)
            payload = cmp_res.get_json()
            self.assertEqual(len(payload["profiles"]), 2)
            self.assertGreaterEqual(len(payload["advantages"]), 4)
            self.assertEqual(len(payload["pair_synergies"]), 1)

        draft_2026 = self.client.post(
            "/api/match/predict",
            json={
                "map": "Corrode",
                "team1": ["Hush", "Miks", "Tejo", "Veto", "Yoru"],
                "team2": ["Clove", "Deadlock", "Gekko", "Vyse", "Waylay"],
            },
        )
        self.assertEqual(draft_2026.status_code, 200)
        self.assertIsNotNone(draft_2026.get_json()["ml_prediction"])


if __name__ == "__main__":
    unittest.main()
