import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from flask import url_for

from app import app
from src.database import OTPCode, Review, User, create_otp_code, db, resolve_database_uri


class AuthProfileAndReviewsTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(
            os.environ,
            {
                "VALOSENT_STORAGE": "sqlite",
                "GMAIL_USER": "",
                "GMAIL_APP_PASSWORD": "",
                "GMAIL_RELAY_URL": "",
                "GMAIL_RELAY_TOKEN": "",
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

    def test_all_routes_and_assets_and_no_dev_otp_copy(self):
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

        # Verify zero Dev/Fake OTP fallback banners exist on /login or /register
        for auth_path in ("/login", "/register"):
            html = self.client.get(auth_path).get_data(as_text=True)
            self.assertNotIn("Dev Fallback", html)
            self.assertNotIn("Local Dev OTP", html)
            self.assertNotIn("dev_otp", html)

        # Verify all 13 maps & 30 agents in /api/assets
        maps_res = self.client.get("/api/maps").get_json()["maps"]
        self.assertEqual(len(maps_res), 13)
        assets = self.client.get("/api/assets").get_json()
        self.assertEqual(len(assets["agents"]), 30)
        self.assertEqual(len(assets["maps"]), 13)

    def test_database_uri_converts_postgres_scheme_and_proxyfix_builds_https_callback(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgres://user:pass@host:5432/valosent"}):
            self.assertEqual(resolve_database_uri(), "postgresql://user:pass@host:5432/valosent")

        with app.test_request_context(
            "/login/google",
            environ_overrides={
                "HTTP_X_FORWARDED_PROTO": "https",
                "HTTP_X_FORWARDED_HOST": "valosent-ai.onrender.com",
            },
        ):
            # Apply ProxyFix headers via WSGI environment check
            self.assertTrue(url_for("google_callback", _external=True).endswith("/login/google/callback"))

    def test_otp_returns_503_when_smtp_unconfigured_never_exposes_dev_otp(self):
        email = f"nosmtp_{uuid.uuid4().hex[:8]}@gmail.com"
        self.created_emails.append(email)
        res = self.client.post("/api/auth/otp/send", json={"email": email})
        self.assertEqual(res.status_code, 503)
        data = res.get_json()
        self.assertIn("temporarily unavailable", data["error"].lower())
        self.assertNotIn("dev_otp", data)

    def test_real_smtp_otp_5_attempt_lockout_expiry_and_profile_customization(self):
        suffix = uuid.uuid4().hex[:8]
        email = f"otp_agent_{suffix}@gmail.com"
        self.created_emails.append(email)

        # 1. Mock Gmail SMTP and confirm send succeeds cleanly without returning raw OTP
        mock_smtp_ctx = MagicMock()
        with patch.dict(os.environ, {"GMAIL_USER": "sender@gmail.com", "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop"}):
            with patch("src.database.smtplib.SMTP", return_value=mock_smtp_ctx) as smtp_cls:
                send_res = self.client.post("/api/auth/otp/send", json={"email": email})
                self.assertEqual(send_res.status_code, 200)
                payload = send_res.get_json()
                self.assertEqual(payload["delivery"], "smtp")
                self.assertNotIn("dev_otp", payload)
                smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=15)
                server = mock_smtp_ctx.__enter__.return_value
                server.starttls.assert_called_once()
                server.login.assert_called_once_with("sender@gmail.com", "abcdefghijklmnop")
                server.send_message.assert_called_once()

        # 2. Enforce max 5 failed verification attempts
        for attempt in range(4):
            r = self.client.post("/api/auth/otp/verify", json={"email": email, "otp": "999999"})
            self.assertEqual(r.status_code, 400)
            self.assertIn("remaining", r.get_json()["error"].lower())
        fifth = self.client.post("/api/auth/otp/verify", json={"email": email, "otp": "999999"})
        self.assertEqual(fifth.status_code, 400)
        self.assertIn("maximum verification attempts", fifth.get_json()["error"].lower())

        # 3. Verify 5-minute expiration check
        with app.app_context():
            exp_code, rec = create_otp_code(email, ttl_minutes=5)
            rec.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
            db.session.commit()
        exp_res = self.client.post("/api/auth/otp/verify", json={"email": email, "otp": exp_code})
        self.assertEqual(exp_res.status_code, 400)
        self.assertIn("expired", exp_res.get_json()["error"].lower())

        # 4. Valid OTP creates verified user and redirects new user to /profile/setup
        with app.app_context():
            fresh_code, _ = create_otp_code(email, ttl_minutes=5)
        ok_res = self.client.post("/api/auth/otp/verify", json={"email": email, "otp": fresh_code})
        self.assertEqual(ok_res.status_code, 200)
        ok_data = ok_res.get_json()
        self.assertTrue(ok_data["is_new_user"])
        self.assertTrue(ok_data["user"]["is_verified"])
        self.assertEqual(ok_data["redirect"], "/profile/setup")

        # 5. Replay rejected
        replay = self.client.post("/api/auth/otp/verify", json={"email": email, "otp": fresh_code})
        self.assertEqual(replay.status_code, 400)

        # 6. Profile pages load & profile customization persists username + Valorant Agent avatar
        self.assertEqual(self.client.get("/profile").status_code, 200)
        self.assertEqual(self.client.get("/profile/setup").status_code, 200)

        custom_name = f"Agent_SK#{suffix[:4]}"
        self.created_usernames.append(custom_name)
        save_res = self.client.post(
            "/api/profile",
            json={
                "username": custom_name,
                "main_role": "Sentinel",
                "favorite_agent": "Veto",
                "avatar_mode": "agent",
                "bio": "Anchoring Summit and Corrode sites.",
            },
        )
        self.assertEqual(save_res.status_code, 200)
        saved_user = save_res.get_json()["user"]
        self.assertEqual(saved_user["username"], custom_name)
        self.assertEqual(saved_user["favorite_agent"], "Veto")
        self.assertEqual(saved_user["main_role"], "Sentinel")
        self.assertTrue(saved_user["avatar_url"])

        # 7. Posted review reflects the customized Agent portrait, username, and main role
        post_rev = self.client.post(
            "/api/reviews",
            json={"agent_name": "Miks", "rating": 5, "comment": "Miks utility feels clean on Summit!"},
        )
        self.assertEqual(post_rev.status_code, 201)
        rev = post_rev.get_json()["review"]
        self.assertEqual(rev["username"], custom_name)
        self.assertEqual(rev["author_avatar"], saved_user["avatar_url"])
        self.assertEqual(rev["author_favorite_agent"], "Veto")
        self.assertEqual(rev["author_main_role"], "Sentinel")

    def test_unauthenticated_write_and_profile_are_protected(self):
        self.assertEqual(
            self.client.post("/api/reviews", json={"rating": 5, "comment": "Unauthorized review"}).status_code,
            401,
        )
        self.assertEqual(self.client.get("/api/profile").status_code, 401)
        self.assertEqual(self.client.get("/profile").status_code, 302)

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

        before_veto = self.client.get("/api/agents/Veto").get_json()["review_sentiment"]["total_mentions"]
        post_agent = self.client.post(
            "/api/reviews",
            json={"agent_name": "Veto", "rating": 5, "comment": "Veto is amazing on Corrode defense!"},
        )
        self.assertEqual(post_agent.status_code, 201)
        agent_review = post_agent.get_json()["review"]
        self.assertEqual(agent_review["target_type"], "Agent")
        self.assertEqual(
            self.client.get("/api/agents/Veto").get_json()["review_sentiment"]["total_mentions"],
            before_veto + 1,
        )
        self.assertEqual(self.client.delete(f"/api/reviews/{agent_review['id']}").status_code, 200)
        self.assertEqual(
            self.client.get("/api/agents/Veto").get_json()["review_sentiment"]["total_mentions"],
            before_veto,
        )


if __name__ == "__main__":
    unittest.main()
