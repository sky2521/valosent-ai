"""SQLite + SQLAlchemy persistence for VALOSENT AI user accounts and community reviews."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

from src.text_processing import clean_review

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "valosent.db"
LOGGER = logging.getLogger(__name__)

db = SQLAlchemy()

_FAST_SVM_CACHE: dict | None = None


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
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
        return check_password_hash(self.password_hash, raw_password)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
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
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.author.username if self.author else "Anonymous",
            "author_role": self.author.role if self.author else "user",
            "agent_name": self.agent_name,
            "target_type": "agent" if self.agent_name else "website",
            "rating": int(self.rating),
            "sentiment_label": self.sentiment_label,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "can_edit": can_manage,
            "can_delete": can_manage,
        }


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
    # Strong star ratings provide clear user intent; mid-range ratings use our trained SVM classifier.
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
            # For 3-star reviews, trust the trained NLP classifier when confident.
            if rating == 3:
                return pred_label if pred_conf >= 0.65 else "Neutral"
            # For 1-2 or 4-5 stars, use the model when it agrees or is overwhelmingly confident.
            if pred_label == star_prior:
                return pred_label
            return star_prior
        except Exception:
            LOGGER.exception("SVM review classification failed; using rating prior.")

    return star_prior


def seed_initial_data() -> None:
    """Populate realistic sample users and website/agent reviews once on an empty database."""
    if User.query.first() is not None:
        return

    now = datetime.now(timezone.utc)
    demo_users = [
        ("valosent_admin", "admin@valosent.ai", "Admin@2026", "admin"),
        ("tactical_jett", "jett@valosent.ai", "Player@2026", "user"),
        ("sentinel_vyse", "vyse@valosent.ai", "Player@2026", "user"),
        ("vct_analyst", "analyst@valosent.ai", "Player@2026", "user"),
    ]
    user_map: dict[str, User] = {}
    for username, email, password, role in demo_users:
        user = User(username=username, email=email, role=role, created_at=now - timedelta(days=20))
        user.set_password(password)
        db.session.add(user)
        user_map[username] = user
    db.session.flush()

    seed_reviews = [
        ("vct_analyst", None, 5, "Positive", "VALOSENT AI's 2021-2026 analytics and 1-click Agent Comparison make prepping VCT drafts so much faster. Clean UI and super accurate ensemble sentiment!", 12),
        ("tactical_jett", None, 4, "Positive", "Love the dark VALORANT aesthetic and the new 5v5 Draft Simulator. Batch CSV review upload saved hours for my esports project.", 9),
        ("sentinel_vyse", None, 3, "Neutral", "Solid platform overall with great agent metrics and XAI highlights. Would love to see live ranked match imports in a future release.", 6),
        ("sentinel_vyse", "Veto", 5, "Positive", "Veto feels amazing on Corrode and Haven! Strong site anchor potential and clean utility synergy with Tejo.", 8),
        ("tactical_jett", "Vyse", 4, "Positive", "Vyse is super fun on Abyss and Split. Her defensive stall feels strong without breaking gunfights.", 7),
        ("vct_analyst", "Miks", 5, "Positive", "Miks brings awesome controller versatility on Corrode and Lotus. Easily one of the cleanest 2026 releases.", 5),
        ("tactical_jett", "Waylay", 4, "Positive", "Waylay's entry pace on Lotus and Split feels smooth and rewarding when paired with an initiator.", 4),
        ("sentinel_vyse", "Yoru", 3, "Neutral", "Yoru's rework is decent on Pearl and Bind, though timing flashes in solo queue still feels inconsistent.", 3),
        ("vct_analyst", "Gekko", 5, "Positive", "Gekko remains super useful for Wingman spike plants on Bind and Sunset. Great team-oriented initiator!", 2),
        ("tactical_jett", "Hush", 2, "Negative", "Hush feels frustrating to play against on Corrode right now; the burst mobility can feel broken in tight choke points.", 1),
    ]

    for username, agent_name, rating, sentiment, comment, days_ago in seed_reviews:
        db.session.add(
            Review(
                user_id=user_map[username].id,
                agent_name=agent_name,
                rating=rating,
                sentiment_label=sentiment,
                comment=comment,
                created_at=now - timedelta(days=days_ago),
            )
        )
    db.session.commit()


def init_db(app) -> None:
    """Attach SQLAlchemy to Flask app, create tables, and seed initial records if empty."""
    db.init_app(app)
    with app.app_context():
        db.create_all()
        seed_initial_data()


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
