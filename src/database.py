"""SQLAlchemy persistence (PostgreSQL / SQLite) for VALOSENT AI accounts, OTP codes, profiles, and reviews."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text
from werkzeug.security import check_password_hash, generate_password_hash

from src.text_processing import clean_review

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "valosent.db"
ENV_PATH = BASE_DIR / ".env"
LOGGER = logging.getLogger(__name__)

db = SQLAlchemy()

_FAST_SVM_CACHE: dict | None = None
_DOTENV_LOADED = False

OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
SMTP_UNAVAILABLE_MESSAGE = (
    "Email OTP service is temporarily unavailable. "
    "Please configure SMTP credentials or use Continue with Google."
)


def load_local_env() -> None:
    """Load key=value pairs from project .env into os.environ without overriding existing vars."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv

        if ENV_PATH.exists():
            load_dotenv(dotenv_path=ENV_PATH, override=False)
            return
    except ImportError:
        pass
    if not ENV_PATH.exists():
        return
    try:
        for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        LOGGER.warning("Could not read .env file at %s", ENV_PATH)


def resolve_database_uri() -> str:
    """Return production PostgreSQL URI (converting postgres:// -> postgresql://) or local SQLite."""
    load_local_env()
    raw = os.environ.get("DATABASE_URL", "").strip()
    if raw:
        if raw.startswith("postgres://"):
            return raw.replace("postgres://", "postgresql://", 1)
        return raw
    return f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    google_id = db.Column(db.String(128), unique=True, nullable=True, index=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    google_avatar_url = db.Column(db.String(500), nullable=True)
    favorite_agent = db.Column(db.String(40), nullable=True)
    main_role = db.Column(db.String(20), nullable=True)
    bio = db.Column(db.String(280), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="user")
    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    reviews = db.relationship(
        "Review",
        back_populates="author",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "avatar_url": self.avatar_url,
            "google_avatar_url": self.google_avatar_url,
            "favorite_agent": self.favorite_agent,
            "main_role": self.main_role,
            "bio": self.bio or "",
            "is_verified": bool(self.is_verified),
            "google_linked": bool(self.google_id),
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OTPCode(db.Model):
    __tablename__ = "otp_codes"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    otp_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    used = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    target_type = db.Column(db.String(16), nullable=False, default="Website")
    agent_name = db.Column(db.String(40), nullable=True, index=True)
    rating = db.Column(db.Integer, nullable=False)
    sentiment_label = db.Column(db.String(16), nullable=False, default="Neutral")
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    author = db.relationship("User", back_populates="reviews")

    def to_dict(self, current_user_id: int | None = None, is_admin: bool = False) -> dict:
        can_manage = bool(current_user_id is not None and (self.user_id == current_user_id or is_admin))
        resolved_target = "Agent" if self.agent_name else (self.target_type or "Website")
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.author.username if self.author else "Anonymous",
            "author_role": self.author.role if self.author else "user",
            "author_avatar": self.author.avatar_url if self.author else None,
            "author_favorite_agent": self.author.favorite_agent if self.author else None,
            "author_main_role": self.author.main_role if self.author else None,
            "author_verified": bool(self.author.is_verified) if self.author else False,
            "agent_name": self.agent_name,
            "target_type": resolved_target,
            "rating": int(self.rating),
            "sentiment_label": self.sentiment_label,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "can_edit": can_manage,
            "can_delete": can_manage,
        }


class AnalyzedReview(db.Model):
    __tablename__ = "analyzed_reviews"

    id = db.Column(db.Integer, primary_key=True)
    review_text = db.Column(db.Text, nullable=False)
    sentiment_label = db.Column(db.String(16), nullable=False)
    derived_score = db.Column(db.Float, nullable=False)
    score_bucket = db.Column(db.Integer, nullable=False)
    agents_json = db.Column(db.Text, nullable=False, default="[]")
    maps_json = db.Column(db.Text, nullable=False, default="[]")
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def generate_unique_username(email: str, preferred_name: str | None = None) -> str:
    """Generate a clean unique username (3-32 chars)."""
    raw = (preferred_name or email.split("@", 1)[0] or "agent").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_#.\-]+", "_", raw).strip("_")
    if len(cleaned) < 3:
        cleaned = f"Agent_{cleaned}" if cleaned else "Valosent_Agent"
    base = cleaned[:26]

    candidate = base
    suffix = 1
    while User.query.filter(func.lower(User.username) == candidate.lower()).first() is not None:
        candidate = f"{base[:22]}_{suffix}"
        suffix += 1
    return candidate


def get_or_create_oauth_or_otp_user(
    email: str,
    *,
    username_hint: str | None = None,
    google_id: str | None = None,
    avatar_url: str | None = None,
) -> tuple[User, bool]:
    """Find or provision a verified user account; returns (user, is_new_user)."""
    clean_email = email.strip().lower()
    user = None
    if google_id:
        user = User.query.filter_by(google_id=google_id).first()
    if user is None:
        user = User.query.filter(func.lower(User.email) == clean_email).first()

    if user is not None:
        changed = False
        if google_id and not user.google_id:
            user.google_id = google_id
            changed = True
        if avatar_url:
            if user.google_avatar_url != avatar_url:
                user.google_avatar_url = avatar_url
                changed = True
            # Only populate avatar_url from Google if the user has not chosen a custom Valorant Agent avatar.
            if not user.avatar_url and not user.favorite_agent:
                user.avatar_url = avatar_url
                changed = True
        if not user.is_verified:
            user.is_verified = True
            changed = True
        if changed:
            db.session.commit()
        return user, False

    user = User(
        username=generate_unique_username(clean_email, preferred_name=username_hint),
        email=clean_email,
        password_hash=None,
        google_id=google_id,
        avatar_url=avatar_url,
        google_avatar_url=avatar_url,
        role="user",
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user, True


def create_otp_code(email: str, ttl_minutes: int = OTP_TTL_MINUTES) -> tuple[str, OTPCode]:
    """Create and persist a hashed 6-digit OTP with a 5-minute TTL, invalidating older codes."""
    clean_email = email.strip().lower()
    OTPCode.query.filter_by(email=clean_email, used=False).update({"used": True})
    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    record = OTPCode(
        email=clean_email,
        otp_hash=generate_password_hash(raw_code),
        expires_at=expires_at,
        attempts=0,
        used=False,
    )
    db.session.add(record)
    db.session.commit()
    return raw_code, record


def verify_otp_code(
    email: str,
    raw_code: str,
    max_attempts: int = OTP_MAX_ATTEMPTS,
) -> tuple[bool, str]:
    """Verify a 6-digit OTP enforcing expiration (5 min), single use, and max 5 attempts."""
    clean_email = email.strip().lower()
    clean_code = re.sub(r"\s+", "", str(raw_code or ""))
    if not re.fullmatch(r"\d{6}", clean_code):
        return False, "Enter a valid 6-digit numeric OTP code."

    record = (
        OTPCode.query.filter_by(email=clean_email, used=False)
        .order_by(OTPCode.id.desc())
        .first()
    )
    if record is None:
        return False, "No active OTP found for this email. Click 'Send OTP' to request a new code."

    now = datetime.now(timezone.utc)
    if now > _ensure_utc(record.expires_at):
        record.used = True
        db.session.commit()
        return False, "This OTP code has expired (5-minute limit). Request a fresh code."

    if int(record.attempts or 0) >= max_attempts:
        record.used = True
        db.session.commit()
        return False, f"Maximum verification attempts ({max_attempts}) exceeded. Request a new OTP code."

    if not check_password_hash(record.otp_hash, clean_code):
        record.attempts = int(record.attempts or 0) + 1
        remaining = max_attempts - record.attempts
        if remaining <= 0:
            record.used = True
            db.session.commit()
            return False, f"Maximum verification attempts ({max_attempts}) exceeded. Request a new OTP code."
        db.session.commit()
        return False, f"Invalid 6-digit OTP code. {remaining} attempt{'s' if remaining != 1 else ''} remaining."

    record.used = True
    db.session.commit()
    return True, "OTP verified successfully."


def is_gmail_smtp_configured() -> bool:
    load_local_env()
    gmail_user = os.environ.get("GMAIL_USER", "").strip()
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    placeholders = {"", "your-gmail@gmail.com", "your-16-char-app-password", "change-me"}
    return gmail_user.lower() not in placeholders and gmail_password.lower() not in placeholders


def send_otp_email(email: str, code: str, ttl_minutes: int = OTP_TTL_MINUTES) -> tuple[bool, str, str]:
    """Send a real Valorant-themed 6-digit OTP HTML email via Gmail SMTP (smtp.gmail.com:587 STARTTLS)."""
    load_local_env()
    clean_email = email.strip().lower()
    if not is_gmail_smtp_configured():
        return False, "smtp_unconfigured", SMTP_UNAVAILABLE_MESSAGE

    gmail_user = os.environ["GMAIL_USER"].strip()
    gmail_password = os.environ["GMAIL_APP_PASSWORD"].strip().replace(" ", "")

    msg = EmailMessage()
    msg["Subject"] = f"VALOSENT AI // Tactical Verification Code: {code}"
    msg["From"] = f"VALOSENT AI Protocol <{gmail_user}>"
    msg["To"] = clean_email
    msg.set_content(
        f"VALOSENT AI // TACTICAL ACCESS VERIFICATION\n\n"
        f"Your 6-digit verification code is: {code}\n"
        f"This single-use code expires in {ttl_minutes} minutes (maximum {OTP_MAX_ATTEMPTS} attempts).\n\n"
        f"If you did not request this sign-in, you can safely ignore this email.\n"
    )
    msg.add_alternative(
        f"""\
        <div style="background:#0F1923;color:#ECE8E1;padding:32px 28px;font-family:'Segoe UI',Arial,sans-serif;border-top:4px solid #FF4655;max-width:520px;margin:0 auto;">
          <div style="font-size:11px;letter-spacing:3px;color:#FF4655;font-weight:700;text-transform:uppercase;">// VALOSENT PROTOCOL · IDENTITY VERIFICATION</div>
          <h2 style="margin:12px 0 8px;color:#ECE8E1;letter-spacing:1.5px;font-size:22px;text-transform:uppercase;">YOUR 6-DIGIT VERIFICATION CODE</h2>
          <p style="color:#9EAAB7;font-size:14px;line-height:1.6;">Enter this one-time tactical verification code to sign in to your VALOSENT AI account:</p>
          <div style="margin:22px 0;padding:18px 26px;background:#162330;border:1px solid rgba(255,70,85,0.55);border-left:4px solid #FF4655;display:inline-block;font-size:34px;letter-spacing:10px;font-weight:800;color:#FF4655;">
            {code}
          </div>
          <p style="color:#9EAAB7;font-size:12px;margin-top:8px;">Expires in <strong style="color:#ECE8E1;">{ttl_minutes} minutes</strong> · Single-use · Max {OTP_MAX_ATTEMPTS} attempts.</p>
          <hr style="border:none;border-top:1px solid rgba(236,232,225,0.12);margin:20px 0 14px;" />
          <p style="color:#6C7C8C;font-size:11px;margin:0;">If you did not request this login code, ignore this message — your account remains secure.</p>
        </div>
        """,
        subtype="html",
    )

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
        return (
            True,
            "smtp",
            f"A 6-digit verification code has been sent to {clean_email}. Check your inbox (expires in {ttl_minutes} min).",
        )
    except Exception:
        LOGGER.exception("Gmail SMTP delivery failed for %s", clean_email)
        return False, "smtp_error", SMTP_UNAVAILABLE_MESSAGE


def _load_fast_svm():
    """Load only the lightweight TF-IDF + Calibrated LinearSVC (~0.5 MB) for instant review classification."""
    global _FAST_SVM_CACHE
    if _FAST_SVM_CACHE is not None:
        return _FAST_SVM_CACHE
    svm_path = BASE_DIR / "models" / "svm_model.pkl"
    vec_path = BASE_DIR / "models" / "tfidf_vectorizer.pkl"
    if not (svm_path.exists() and vec_path.exists()):
        _FAST_SVM_CACHE = {}
        return _FAST_SVM_CACHE
    try:
        import joblib

        _FAST_SVM_CACHE = {
            "model": joblib.load(svm_path),
            "vectorizer": joblib.load(vec_path),
        }
    except Exception:
        LOGGER.exception("Fast SVM loader failed; falling back to star-rating sentiment mapping.")
        _FAST_SVM_CACHE = {}
    return _FAST_SVM_CACHE


def classify_review_sentiment(comment: str, rating: int) -> str:
    """Automatically classify a submitted community review into Positive, Neutral, or Negative."""
    if rating >= 4:
        star_prior = "Positive"
    elif rating <= 2:
        star_prior = "Negative"
    else:
        star_prior = "Neutral"

    cleaned = clean_review(comment)
    if not cleaned:
        return star_prior

    svm_bundle = _load_fast_svm()
    if svm_bundle:
        try:
            vec = svm_bundle["vectorizer"].transform([cleaned])
            model = svm_bundle["model"]
            probs = model.predict_proba(vec)[0]
            classes = [str(c) for c in model.classes_]
            best_idx = int(probs.argmax())
            pred_label = classes[best_idx]
            pred_conf = float(probs[best_idx])
            if rating == 3:
                return pred_label if pred_conf >= 0.65 else "Neutral"
            if pred_label == star_prior:
                return pred_label
            return star_prior
        except Exception:
            LOGGER.exception("SVM review classification failed; using rating prior.")

    return star_prior


def _migrate_schema() -> None:
    """Safely add any missing columns to existing SQLite or PostgreSQL tables."""
    engine = db.engine
    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "sqlite":
            # 1. Users table columns
            user_cols = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            if user_cols:
                col_map = {row[1]: row for row in user_cols}
                if int(col_map["password_hash"][3]) == 1:
                    conn.execute(text("PRAGMA foreign_keys=OFF"))
                    conn.execute(
                        text(
                            """
                            CREATE TABLE users_new (
                                id INTEGER NOT NULL PRIMARY KEY,
                                username VARCHAR(40) NOT NULL UNIQUE,
                                email VARCHAR(120) NOT NULL UNIQUE,
                                password_hash VARCHAR(255),
                                google_id VARCHAR(128) UNIQUE,
                                avatar_url VARCHAR(500),
                                google_avatar_url VARCHAR(500),
                                favorite_agent VARCHAR(40),
                                main_role VARCHAR(20),
                                bio VARCHAR(280),
                                role VARCHAR(20) NOT NULL DEFAULT 'user',
                                is_verified BOOLEAN NOT NULL DEFAULT 0,
                                created_at DATETIME NOT NULL
                            )
                            """
                        )
                    )
                    def _col_or(name: str, default_sql: str) -> str:
                        return name if name in col_map else default_sql

                    conn.execute(
                        text(
                            f"""
                            INSERT INTO users_new (
                                id, username, email, password_hash, google_id, avatar_url,
                                google_avatar_url, favorite_agent, main_role, bio, role, is_verified, created_at
                            )
                            SELECT
                                id, username, email, password_hash,
                                {_col_or('google_id', 'NULL')},
                                {_col_or('avatar_url', 'NULL')},
                                {_col_or('google_avatar_url', 'NULL')},
                                {_col_or('favorite_agent', 'NULL')},
                                {_col_or('main_role', 'NULL')},
                                {_col_or('bio', 'NULL')},
                                role,
                                {_col_or('is_verified', '1')},
                                created_at
                            FROM users
                            """
                        )
                    )
                    conn.execute(text("DROP TABLE users"))
                    conn.execute(text("ALTER TABLE users_new RENAME TO users"))
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"))
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"))
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)"))
                    conn.execute(text("PRAGMA foreign_keys=ON"))
                else:
                    for col_name, col_ddl in (
                        ("google_id", "VARCHAR(128)"),
                        ("avatar_url", "VARCHAR(500)"),
                        ("google_avatar_url", "VARCHAR(500)"),
                        ("favorite_agent", "VARCHAR(40)"),
                        ("main_role", "VARCHAR(20)"),
                        ("bio", "VARCHAR(280)"),
                        ("is_verified", "BOOLEAN NOT NULL DEFAULT 0"),
                    ):
                        if col_name not in col_map:
                            conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_ddl}"))

            # 2. OTPCode attempts column
            otp_cols = conn.execute(text("PRAGMA table_info(otp_codes)")).fetchall()
            if otp_cols and "attempts" not in {row[1] for row in otp_cols}:
                conn.execute(text("ALTER TABLE otp_codes ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"))

            # 3. Review target_type column
            review_cols = conn.execute(text("PRAGMA table_info(reviews)")).fetchall()
            if review_cols and "target_type" not in {row[1] for row in review_cols}:
                conn.execute(
                    text("ALTER TABLE reviews ADD COLUMN target_type VARCHAR(16) NOT NULL DEFAULT 'Website'")
                )
                conn.execute(
                    text(
                        """
                        UPDATE reviews
                        SET target_type = CASE
                            WHEN agent_name IS NOT NULL AND TRIM(agent_name) != '' THEN 'Agent'
                            ELSE 'Website'
                        END
                        """
                    )
                )
        elif dialect == "postgresql":
            for stmt in (
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_avatar_url VARCHAR(500)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_agent VARCHAR(40)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS main_role VARCHAR(20)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS bio VARCHAR(280)",
                "ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS target_type VARCHAR(16) NOT NULL DEFAULT 'Website'",
            ):
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass


def seed_initial_data() -> None:
    """Populate realistic sample users and website/agent reviews once on an empty database."""
    if User.query.first() is not None:
        return

    from src.valorant_assets import get_agent_asset

    now = datetime.now(timezone.utc)
    demo_users = [
        ("valosent_admin", "admin@valosent.ai", "Admin@2026", "admin", "Miks", "Controller", "VALOSENT AI Platform Architect & VCT Meta Analyst"),
        ("tactical_jett", "jett@valosent.ai", "Player@2026", "user", "Jett", "Duelist", "Entry fragger grinding Ascendant/Immortal queues."),
        ("sentinel_vyse", "vyse@valosent.ai", "Player@2026", "user", "Vyse", "Sentinel", "Site anchor specialist on Corrode, Abyss, and Split."),
        ("vct_analyst", "analyst@valosent.ai", "Player@2026", "user", "Veto", "Sentinel", "Tracking pro VCT draft compositions and patch shifts."),
    ]
    user_map: dict[str, User] = {}
    for username, email, password, role, fav_agent, main_role, bio in demo_users:
        asset = get_agent_asset(fav_agent, main_role)
        user = User(
            username=username,
            email=email,
            role=role,
            avatar_url=asset.get("icon") or asset.get("fallback_icon"),
            favorite_agent=fav_agent,
            main_role=main_role,
            bio=bio,
            is_verified=True,
            created_at=now - timedelta(days=20),
        )
        user.set_password(password)
        db.session.add(user)
        user_map[username] = user
    db.session.flush()

    seed_reviews = [
        ("vct_analyst", None, 5, "Positive", "VALOSENT AI's 2021-2026 analytics across all 13 maps including Summit and Corrode make prepping VCT drafts effortless. Authentic HUD and super accurate ensemble sentiment!", 12),
        ("tactical_jett", None, 4, "Positive", "Love the pro-grade VALORANT tactical HUD, dynamic map backgrounds, and the 5v5 Draft Simulator. Batch CSV review upload saved hours for my esports project.", 9),
        ("sentinel_vyse", None, 3, "Neutral", "Solid platform overall with great agent metrics, official Riot artwork, and XAI highlights. Would love to see live ranked match imports in a future release.", 6),
        ("sentinel_vyse", "Veto", 5, "Positive", "Veto feels amazing on Corrode, Summit, and Haven! Strong site anchor potential and clean utility synergy with Tejo.", 8),
        ("tactical_jett", "Vyse", 4, "Positive", "Vyse is super fun on Abyss and Split. Her defensive stall feels strong without breaking gunfights.", 7),
        ("vct_analyst", "Miks", 5, "Positive", "Miks brings awesome controller versatility on Summit, Corrode, and Lotus. Easily one of the cleanest 2026 releases.", 5),
        ("tactical_jett", "Waylay", 4, "Positive", "Waylay's entry pace on Lotus and Split feels smooth and rewarding when paired with an initiator.", 4),
        ("sentinel_vyse", "Yoru", 3, "Neutral", "Yoru's rework is decent on Pearl and Bind, though timing flashes in solo queue still feels inconsistent.", 3),
        ("vct_analyst", "Gekko", 5, "Positive", "Gekko remains super useful for Wingman spike plants on Bind and Sunset. Great team-oriented initiator!", 2),
        ("tactical_jett", "Hush", 2, "Negative", "Hush feels frustrating to play against on Corrode right now; the burst mobility can feel broken in tight choke points.", 1),
    ]

    for username, agent_name, rating, sentiment, comment, days_ago in seed_reviews:
        db.session.add(
            Review(
                user_id=user_map[username].id,
                target_type="Agent" if agent_name else "Website",
                agent_name=agent_name,
                rating=rating,
                sentiment_label=sentiment,
                comment=comment,
                created_at=now - timedelta(days=days_ago),
            )
        )
    db.session.commit()


def init_db(app) -> None:
    """Attach SQLAlchemy to Flask app, migrate/create tables, and seed initial records if empty."""
    load_local_env()
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _migrate_schema()
        db.create_all()
        seed_initial_data()


def record_analyzed_review(
    review_text: str,
    sentiment_label: str,
    derived_score: float,
    agents: list[str] | None = None,
    maps: list[str] | None = None,
) -> AnalyzedReview:
    """Persist an analyzed review so live 100k+ sentiment counters update in real time."""
    bucket = max(0, min(10, int(round(float(derived_score)))))
    rec = AnalyzedReview(
        review_text=str(review_text)[:2000],
        sentiment_label=str(sentiment_label),
        derived_score=round(float(derived_score), 2),
        score_bucket=bucket,
        agents_json=json.dumps(list(agents or [])),
        maps_json=json.dumps(list(maps or [])),
    )
    db.session.add(rec)
    db.session.commit()
    return rec


def get_live_analyzed_review_rows(db_path: Path | None = None) -> list[dict]:
    """Read live analyzed reviews from SQL DB so sentiment charts & agent counts update immediately."""
    try:
        from flask import has_app_context

        if has_app_context():
            rows = AnalyzedReview.query.all()
            return [
                {
                    "sentiment_label": row.sentiment_label,
                    "derived_score": float(row.derived_score),
                    "score_bucket": int(row.score_bucket),
                    "agents": json.loads(row.agents_json or "[]"),
                    "maps": json.loads(row.maps_json or "[]"),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
    except Exception:
        pass

    target = db_path or DEFAULT_DB_PATH
    if not target.exists():
        return []
    try:
        conn = sqlite3.connect(str(target))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT sentiment_label, derived_score, score_bucket, agents_json, maps_json, created_at FROM analyzed_reviews"
            ).fetchall()
            return [
                {
                    "sentiment_label": r["sentiment_label"],
                    "derived_score": float(r["derived_score"]),
                    "score_bucket": int(r["score_bucket"]),
                    "agents": json.loads(r["agents_json"] or "[]"),
                    "maps": json.loads(r["maps_json"] or "[]"),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def get_community_agent_review_rows(db_path: Path | None = None) -> list[dict]:
    """Read stored agent reviews directly from SQLite so analytics/sentiment pages stay live."""
    target = db_path or DEFAULT_DB_PATH
    if not target.exists():
        return []
    try:
        conn = sqlite3.connect(str(target))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT agent_name, sentiment_label, comment, created_at
                FROM reviews
                WHERE agent_name IS NOT NULL AND TRIM(agent_name) != ''
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except sqlite3.Error:
        return []
