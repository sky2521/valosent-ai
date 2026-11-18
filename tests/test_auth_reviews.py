import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import app
from src.database import OTPCode, Review, User, create_otp_code, db


class AuthAndCommunityReviewsTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(
            os.environ,
            {
                "VALOSENT_STORAGE": "sqlite",
                "GMAIL_USER": "",
                "GMAIL_APP_PASSWORD": "",
                "GOOGLE_CLIENT_ID": "",
                "GOOGLE_CLIENT_SECRET": "",
            },
        )
        self._env_patch.start()
        self.client = app.test_client()
        self.created_usernames: list[str] = []
        self.created_emails: list[str] = []

    def tearDown(self):
        with app.app_context():
            for username in self.created_usernames:
                user = User.query.filter_by(username=username).first()
                if user:
                    db.session.delete(user)
            for email in self.created_emails:
                user = User.query.filter_by(email=email).first()
                if user:
                    db.session.delete(user)
                OTPCode.query.filter_by(email=email).delete()
            db.session.commit()
        self._env_patch.stop()

    def _unique_user(self, prefix: str = "tester") -> tuple[str, str, str]:
        suffix = uuid.uuid4().hex[:8]
        username = f"{prefix}_{suffix}"
        email = f"{username}@example.com"
        password = "TestPassword@2026"
        self.created_usernames.append(username)
        self.created_emails.append(email)
        return username, email, password

    def test_all_routes_and_assets_and_13_maps_load(self):
        for path in (
            "/",
            "/overview",
            "/maps",
            "/maps/Summit",
            "/agents",
            "/agents/Veto",
            "/recommend",
            "/recommendations",
            "/compare",
            "/sentiment",
            "/models",
            "/model-lab",
            "/reviews",
            "/about",
            "/login",
            "/register",
        ):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Route {path} failed with {res.status_code}")

        # Verify all 13 maps incl. Summit & Corrode
        maps_res = self.client.get("/api/maps").get_json()["maps"]
        self.assertEqual(len(maps_res), 13)
        for expected_map in ("Summit", "Corrode", "Abyss", "Sunset", "Lotus", "Pearl", "Fracture", "Breeze", "Icebox", "Ascent", "Split", "Haven", "Bind"):
            self.assertIn(expected_map, maps_res)

        # Verify /api/assets returns all 30 agents + 13 maps + 4 roles
        assets = self.client.get("/api/assets").get_json()
        self.assertEqual(len(assets["agents"]), 30)
        self.assertEqual(len(assets["maps"]), 13)
        self.assertEqual(len(assets["roles"]), 4)
        self.assertIn("Veto", assets["agents"])
        self.assertIn("Summit", assets["maps"])
        self.assertTrue(assets["maps"]["Summit"]["splash"])
        self.assertTrue(assets["agents"]["Veto"]["portrait"])

        # Verify Summit map endpoint, recommendations & 5v5 draft predictor work cleanly
        summit_map = self.client.get("/api/maps/Summit")
        self.assertEqual(summit_map.status_code, 200)
        self.assertIn("assets", summit_map.get_json())

        summit_rec = self.client.get("/api/recommend?map=Summit")
        self.assertEqual(summit_rec.status_code, 200)
        self.assertGreater(len(summit_rec.get_json()["recommendations"]), 0)

        draft_res = self.client.post(
            "/api/match/predict",
            json={
                "map": "Summit",
                "team1": ["Miks", "Sova", "Tejo", "Veto", "Waylay"],
                "team2": ["Fade", "Jett", "KAY/O", "Omen", "Vyse"],
            },
        )
        self.assertEqual(draft_res.status_code, 200)
        self.assertIsNotNone(draft_res.get_json().get("ml_prediction"))

        # Verify seeded reviews
        rev_data = self.client.get("/api/reviews").get_json()
        self.assertGreaterEqual(rev_data["summary"]["total_reviews"], 8)
        self.assertGreaterEqual(rev_data["summary"]["website_reviews"], 2)
        self.assertGreaterEqual(rev_data["summary"]["agent_reviews"], 5)

    def test_google_oauth_unconfigured_shows_helpful_setup_prompt(self):
        res = self.client.get("/login/google")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"GOOGLE_CLIENT_ID", res.data)
        self.assertIn(b"/login/google/callback", res.data)

    def test_gmail_otp_dev_fallback_expiry_and_single_use_login(self):
        suffix = uuid.uuid4().hex[:8]
        email = f"otp_agent_{suffix}@gmail.com"
        self.created_emails.append(email)

        # 1. Send OTP via API (dev fallback mode since GMAIL_USER is blank)
        send_res = self.client.post("/api/auth/otp/send", json={"email": email})
        self.assertEqual(send_res.status_code, 200)
        send_payload = send_res.get_json()
        self.assertEqual(send_payload["status"], "sent")
        self.assertEqual(send_payload["delivery"], "console_dev")
        self.assertEqual(send_payload["expires_in_seconds"], 300)

        # 2. Wrong OTP fails cleanly
        wrong_res = self.client.post("/api/auth/otp/verify", json={"email": email, "otp": "999999"})
        self.assertEqual(wrong_res.status_code, 400)

        # 3. Create known OTP code, verify expiration enforcement first
        with app.app_context():
            code = create_otp_code(email, ttl_minutes=5)
            rec = OTPCode.query.filter_by(email=email, used=False).order_by(OTPCode.id.desc()).first()
            rec.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            db.session.commit()

        expired_res = self.client.post("/api/auth/otp/verify", json={"email": email, "otp": code})
        self.assertEqual(expired_res.status_code, 400)
        self.assertIn("expired", expired_res.get_json()["error"].lower())

        # 4. Create valid OTP code and log in
        with app.app_context():
            fresh_code = create_otp_code(email, ttl_minutes=5)

        ok_res = self.client.post("/api/auth/otp/verify", json={"email": email, "otp": fresh_code})
        self.assertEqual(ok_res.status_code, 200)
        ok_data = ok_res.get_json()
        self.assertEqual(ok_data["status"], "ok")
        self.assertTrue(ok_data["user"]["is_verified"])
        self.assertEqual(ok_data["user"]["email"], email)

        # 5. Single-use enforcement: replaying the exact same OTP must fail
        replay_res = self.client.post("/api/auth/otp/verify", json={"email": email, "otp": fresh_code})
        self.assertEqual(replay_res.status_code, 400)

        # 6. Authenticated OTP user can immediately post a review
        post_res = self.client.post(
            "/api/reviews",
            json={"agent_name": "Miks", "rating": 5, "comment": "Miks feels incredible on Summit!"},
        )
        self.assertEqual(post_res.status_code, 201)
        self.assertEqual(post_res.get_json()["review"]["target_type"], "Agent")

    def test_unauthenticated_write_is_blocked(self):
        res = self.client.post(
            "/api/reviews",
            json={"rating": 5, "comment": "Unauthorized attempt should fail cleanly."},
        )
        self.assertEqual(res.status_code, 401)

    def test_register_login_logout_and_review_crud_updates_agent_sentiment(self):
        username, email, password = self._unique_user("veto_fan")

        reg_res = self.client.post(
            "/register",
            data={
                "username": username,
                "email": email,
                "password": password,
                "confirm_password": password,
            },
            follow_redirects=False,
        )
        self.assertEqual(reg_res.status_code, 302)
        self.assertIn("/reviews", reg_res.headers["Location"])

        with app.app_context():
            user = User.query.filter_by(username=username).first()
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, password)
            self.assertTrue(user.check_password(password))

        before_veto = self.client.get("/api/agents/Veto").get_json()["review_sentiment"]["total_mentions"]

        post_agent = self.client.post(
            "/api/reviews",
            json={
                "agent_name": "Veto",
                "rating": 5,
                "comment": "Veto is amazing and super strong on Corrode defense!",
            },
        )
        self.assertEqual(post_agent.status_code, 201)
        agent_review = post_agent.get_json()["review"]
        self.assertEqual(agent_review["agent_name"], "Veto")
        self.assertEqual(agent_review["target_type"], "Agent")
        self.assertEqual(agent_review["sentiment_label"], "Positive")
        self.assertTrue(agent_review["can_edit"])

        after_veto = self.client.get("/api/agents/Veto").get_json()["review_sentiment"]["total_mentions"]
        self.assertEqual(after_veto, before_veto + 1)

        post_site = self.client.post(
            "/api/reviews",
            json={
                "agent_name": None,
                "rating": 4,
                "comment": "Really enjoy the new dark crimson dashboard and quick agent matchups.",
            },
        )
        self.assertEqual(post_site.status_code, 201)
        site_review = post_site.get_json()["review"]
        self.assertIsNone(site_review["agent_name"])
        self.assertEqual(site_review["target_type"], "Website")

        edit_res = self.client.put(
            f"/api/reviews/{agent_review['id']}",
            json={
                "rating": 1,
                "comment": "Actually Veto feels awful and frustrating after the nerf.",
            },
        )
        self.assertEqual(edit_res.status_code, 200)
        edited = edit_res.get_json()["review"]
        self.assertEqual(edited["rating"], 1)
        self.assertEqual(edited["sentiment_label"], "Negative")

        mine_res = self.client.get("/api/reviews?mine=1")
        self.assertEqual(mine_res.status_code, 200)
        self.assertEqual(mine_res.get_json()["filtered_count"], 2)

        self.client.get("/logout")
        other_client = app.test_client()
        u2, e2, p2 = self._unique_user("other_user")
        other_client.post(
            "/register",
            data={"username": u2, "email": e2, "password": p2, "confirm_password": p2},
        )
        self.assertEqual(other_client.delete(f"/api/reviews/{agent_review['id']}").status_code, 403)
        self.assertEqual(
            other_client.put(
                f"/api/reviews/{agent_review['id']}",
                json={"rating": 5, "comment": "Trying to hijack another user's review."},
            ).status_code,
            403,
        )

        bad_login = self.client.post("/login", data={"identifier": email, "password": "wrong"})
        self.assertEqual(bad_login.status_code, 200)
        self.assertIn(b"Invalid", bad_login.data)

        good_login = self.client.post("/login", data={"identifier": email, "password": password})
        self.assertEqual(good_login.status_code, 302)

        self.assertEqual(self.client.delete(f"/api/reviews/{agent_review['id']}").status_code, 200)
        self.client.delete(f"/api/reviews/{site_review['id']}")

        final_veto = self.client.get("/api/agents/Veto").get_json()["review_sentiment"]["total_mentions"]
        self.assertEqual(final_veto, before_veto)


if __name__ == "__main__":
    unittest.main()
