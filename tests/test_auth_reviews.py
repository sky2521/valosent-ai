import os
import unittest
import uuid
from unittest.mock import patch

from app import app
from src.database import Review, User, db


class AuthAndCommunityReviewsTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(os.environ, {"VALOSENT_USE_SQLITE": "1"})
        self._env_patch.start()
        self.client = app.test_client()
        self.created_usernames: list[str] = []

    def tearDown(self):
        with app.app_context():
            for username in self.created_usernames:
                user = User.query.filter_by(username=username).first()
                if user:
                    db.session.delete(user)
            db.session.commit()
        self._env_patch.stop()

    def _unique_user(self, prefix: str = "tester") -> tuple[str, str, str]:
        suffix = uuid.uuid4().hex[:8]
        username = f"{prefix}_{suffix}"
        email = f"{username}@example.com"
        password = "TestPassword@2026"
        self.created_usernames.append(username)
        return username, email, password

    def test_auth_pages_and_seeded_reviews_load(self):
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/register").status_code, 200)
        self.assertEqual(self.client.get("/reviews").status_code, 200)

        res = self.client.get("/api/reviews")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertGreaterEqual(data["summary"]["total_reviews"], 8)
        self.assertGreaterEqual(data["summary"]["website_reviews"], 2)
        self.assertGreaterEqual(data["summary"]["agent_reviews"], 5)

    def test_unauthenticated_write_is_blocked(self):
        res = self.client.post(
            "/api/reviews",
            json={"rating": 5, "comment": "Unauthorized attempt should fail cleanly."},
        )
        self.assertEqual(res.status_code, 401)

    def test_register_login_logout_and_review_crud_updates_agent_sentiment(self):
        username, email, password = self._unique_user("veto_fan")

        # 1. Register & auto-login
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

        # Verify password is securely hashed (not stored plaintext)
        with app.app_context():
            user = User.query.filter_by(username=username).first()
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, password)
            self.assertTrue(user.check_password(password))

        # 2. Check Veto's baseline mention count before submitting a new review
        before_veto = self.client.get("/api/agents/Veto").get_json()["review_sentiment"]["total_mentions"]

        # 3. Submit an Agent review for Veto + a Website review
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
        self.assertEqual(agent_review["sentiment_label"], "Positive")
        self.assertTrue(agent_review["can_edit"])

        # Verify /api/agents/Veto live mention count incremented by +1
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
        self.assertEqual(site_review["target_type"], "website")

        # 4. Edit own agent review (flip to 1-star negative)
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

        # 5. Filter by mine=1
        mine_res = self.client.get("/api/reviews?mine=1")
        self.assertEqual(mine_res.status_code, 200)
        self.assertEqual(mine_res.get_json()["filtered_count"], 2)

        # 6. Logout and verify another user cannot edit/delete this review (403)
        self.client.get("/logout")
        other_client = app.test_client()
        u2, e2, p2 = self._unique_user("other_user")
        other_client.post(
            "/register",
            data={"username": u2, "email": e2, "password": p2, "confirm_password": p2},
        )
        forbidden_del = other_client.delete(f"/api/reviews/{agent_review['id']}")
        self.assertEqual(forbidden_del.status_code, 403)
        forbidden_put = other_client.put(
            f"/api/reviews/{agent_review['id']}",
            json={"rating": 5, "comment": "Trying to hijack another user's review."},
        )
        self.assertEqual(forbidden_put.status_code, 403)

        # 7. Log back in as original author using email, then delete both reviews
        bad_login = self.client.post("/login", data={"identifier": email, "password": "wrong"})
        self.assertEqual(bad_login.status_code, 200)
        self.assertIn(b"Invalid", bad_login.data)

        good_login = self.client.post("/login", data={"identifier": email, "password": password})
        self.assertEqual(good_login.status_code, 302)

        del_res = self.client.delete(f"/api/reviews/{agent_review['id']}")
        self.assertEqual(del_res.status_code, 200)
        self.client.delete(f"/api/reviews/{site_review['id']}")

        # Verify Veto's mention count returned to baseline
        final_veto = self.client.get("/api/agents/Veto").get_json()["review_sentiment"]["total_mentions"]
        self.assertEqual(final_veto, before_veto)


if __name__ == "__main__":
    unittest.main()
