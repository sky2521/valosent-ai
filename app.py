from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from authlib.integrations.flask_client import OAuth
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from sqlalchemy import func
from werkzeug.exceptions import RequestEntityTooLarge

from src.database import (
    OTPCode,
    Review,
    User,
    classify_review_sentiment,
    create_otp_code,
    db,
    get_or_create_oauth_or_otp_user,
    init_db,
    is_gmail_smtp_configured,
    load_local_env,
    record_analyzed_review,
    send_otp_email,
    verify_otp_code,
)
from src.supabase_backend import (
    create_supabase_review,
    delete_supabase_review,
    is_supabase_enabled,
    list_supabase_reviews,
    supabase_login,
    supabase_logout,
    supabase_refresh_session,
    supabase_signup,
    update_supabase_review,
)
from src.valorant_assets import get_agent_asset, get_all_assets, get_map_asset

from src.analytics import (
    get_agent_comparison,
    get_agent_comparison_summary,
    get_agent_stats,
    get_agent_synergy,
    get_agents,
    get_best_agents_for_map,
    get_best_team_compositions,
    get_dataset_summary,
    get_map_agent_stats,
    get_map_stats,
    get_maps,
    get_roles,
    normalize_name,
)
from src.inference import (
    MAX_BATCH_REVIEWS,
    MAX_LENGTH,
    align_probabilities,
    analyze_reviews_batch,
    load_assets as _load_inference_assets,
    predict_match_draft,
    predict_single_review,
)
from src.review_analysis import (
    analyze_review_context,
    get_agent_catalog,
    get_agent_review_sentiment,
    get_map_sentiment_summary,
    get_sentiment_by_agent,
)
from src.sentiment import get_score_distribution, get_sentiment_distribution
from src.text_processing import clean_review

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"

load_local_env()

app = Flask(__name__)
# Limit incoming request size before Flask reads JSON or CSV payloads into memory.
app.config["MAX_CONTENT_LENGTH"] = 2_000_000
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "valosent-ai-secure-session-key-2026")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{(BASE_DIR / 'valosent.db').as_posix()}",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

init_db(app)

oauth = OAuth(app)
_GOOGLE_OAUTH_PLACEHOLDERS = {
    "",
    "your-google-client-id.apps.googleusercontent.com",
    "your-google-client-secret",
    "change-me",
}


def is_google_oauth_configured() -> bool:
    load_local_env()
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    csec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    return cid.lower() not in _GOOGLE_OAUTH_PLACEHOLDERS and csec.lower() not in _GOOGLE_OAUTH_PLACEHOLDERS


def _get_google_oauth_client():
    if not is_google_oauth_configured():
        return None
    client = oauth.create_client("google")
    if client is None:
        client = oauth.register(
            name="google",
            client_id=os.environ["GOOGLE_CLIENT_ID"].strip(),
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"].strip(),
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    return client


login_manager = LoginManager()
login_manager.login_view = "login_page"
login_manager.login_message_category = "info"
login_manager.init_app(app)


class SupabaseSessionUser(UserMixin):
    """Lightweight Flask-Login user backed by a verified Supabase Auth session."""

    def __init__(self, user_id: str, username: str, email: str, role: str = "user"):
        self.id = str(user_id)
        self.username = username
        self.email = email
        self.role = role
        self.avatar_url = None
        self.is_verified = True


@app.context_processor
def inject_auth_context():
    return {
        "supabase_enabled": is_supabase_enabled(),
        "google_oauth_configured": is_google_oauth_configured(),
        "gmail_smtp_configured": is_gmail_smtp_configured(),
    }


@login_manager.user_loader
def load_user(user_id: str):
    if is_supabase_enabled():
        sb_user = session.get("sb_user")
        if isinstance(sb_user, dict) and str(sb_user.get("id")) == str(user_id):
            return SupabaseSessionUser(
                user_id=sb_user["id"],
                username=sb_user.get("username", "player"),
                email=sb_user.get("email", ""),
                role=sb_user.get("role", "user"),
            )
        return None
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def _get_supabase_access_token() -> str | None:
    return session.get("sb_access_token")


def _call_supabase_with_refresh(fn):
    """Run a Supabase authenticated action and retry once with refreshed JWT on 401."""
    token = _get_supabase_access_token()
    if not token:
        return 401, {"error": "Session expired. Please log in again."}
    status, data = fn(token)
    if status == 401 and session.get("sb_refresh_token"):
        refreshed = supabase_refresh_session(session["sb_refresh_token"])
        if refreshed:
            session["sb_access_token"] = refreshed["access_token"]
            session["sb_refresh_token"] = refreshed["refresh_token"]
            return fn(refreshed["access_token"])
    return status, data


@login_manager.unauthorized_handler
def handle_unauthorized():
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"error": "Authentication required. Please log in to continue."}), 401
    return redirect(url_for("login_page", next=request.full_path.rstrip("?")))


LOGGER = logging.getLogger(__name__)
MAX_REVIEW_LENGTH = 5000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_safe_redirect_url(target: str | None) -> bool:
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and target.startswith("/")


def _canonical_agent_or_none(raw_agent: str | None) -> tuple[str | None, str | None]:
    """Validate optional agent name against catalog; returns (canonical_name, error_message)."""
    value = str(raw_agent or "").strip()
    if not value or value.casefold() in {"website", "none", "general", "valosent ai"}:
        return None, None
    target_key = normalize_name(value)
    for item in get_agent_catalog():
        if normalize_name(item["agent"]) == target_key:
            return item["agent"], None
    return None, f"Unknown VALORANT agent: {value}"


def _build_reviews_summary(all_reviews: list[Review]) -> dict:
    total = len(all_reviews)
    website_count = sum(1 for r in all_reviews if not r.agent_name)
    agent_count = total - website_count
    avg_rating = round(sum(r.rating for r in all_reviews) / total, 2) if total else 0.0
    pos_count = sum(1 for r in all_reviews if r.sentiment_label == "Positive")
    neu_count = sum(1 for r in all_reviews if r.sentiment_label == "Neutral")
    neg_count = sum(1 for r in all_reviews if r.sentiment_label == "Negative")
    unique_authors = len({r.user_id for r in all_reviews})
    return {
        "total_reviews": total,
        "website_reviews": website_count,
        "agent_reviews": agent_count,
        "average_rating": avg_rating,
        "positive_count": pos_count,
        "neutral_count": neu_count,
        "negative_count": neg_count,
        "positive_percentage": round(pos_count / total * 100, 1) if total else 0.0,
        "neutral_percentage": round(neu_count / total * 100, 1) if total else 0.0,
        "negative_percentage": round(neg_count / total * 100, 1) if total else 0.0,
        "unique_authors": unique_authors,
    }


def load_assets(force_reload: bool = False) -> dict:
    """Delegate model loading to src.inference (kept here for clean API & test patching)."""
    return _load_inference_assets(force_reload=force_reload)


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(_error):
    message = "Request body is too large. Submit a review of 5,000 characters or fewer (or a CSV under 2 MB)."
    return jsonify({"error": message}), 413


def enrich_review_context(review: str) -> dict:
    try:
        analysis = analyze_review_context(review)
    except (FileNotFoundError, ValueError) as error:
        return {
            "agents": [],
            "maps": [],
            "topics": {},
            "agent_detection_message": "Agent catalog is unavailable.",
            "map_detection_message": "Map catalog is unavailable.",
            "aspect_method": f"Entity analysis unavailable: {error}",
        }
    for detected in analysis["agents"]:
        try:
            historical = get_agent_stats(detected["agent"])
        except FileNotFoundError:
            historical = None
        detected["historical_performance"] = historical
        detected["performance_status"] = "available" if historical else "insufficient_data"
    return analysis


@app.route("/")
def index():
    return render_template("dashboard.html", active_page="dashboard")


@app.route("/dashboard")
@app.route("/overview")
@app.route("/maps")
@app.route("/agents")
@app.route("/recommend")
@app.route("/recommendations")
@app.route("/compare")
@app.route("/models")
@app.route("/model-lab")
@app.route("/about")
def analytics_page():
    route_aliases = {
        "overview": "dashboard",
        "recommendations": "recommend",
        "model-lab": "models",
    }
    raw_page = request.path.strip("/") or "dashboard"
    active_page = route_aliases.get(raw_page, raw_page)
    return render_template("dashboard.html", active_page=active_page)


@app.route("/maps/<map_name>")
def map_detail_page(map_name: str):
    return render_template("dashboard.html", active_page="maps", selected_map=map_name)


@app.route("/agents/<path:agent_name>")
def agent_detail_page(agent_name: str):
    return render_template("dashboard.html", active_page="agents", selected_agent=agent_name)


@app.route("/sentiment")
def sentiment_page():
    return render_template("dashboard.html", active_page="sentiment")


@app.route("/register", methods=["GET", "POST"])
def register_page():
    if current_user.is_authenticated:
        return redirect(url_for("reviews_page"))

    error = None
    info_message = None
    form_values = {"username": "", "email": ""}
    if request.method == "POST":
        username = str(request.form.get("username", "")).strip()
        email = str(request.form.get("email", "")).strip().lower()
        password = str(request.form.get("password", ""))
        confirm_password = str(request.form.get("confirm_password", ""))
        form_values = {"username": username, "email": email}

        if not USERNAME_PATTERN.match(username):
            error = "Username must be 3–32 characters using only letters, numbers, or underscores."
        elif not EMAIL_PATTERN.match(email):
            error = "Please enter a valid email address."
        elif len(password) < 6:
            error = "Password must be at least 6 characters long."
        elif confirm_password and password != confirm_password:
            error = "Passwords do not match."
        elif is_supabase_enabled():
            res = supabase_signup(email=email, password=password, username=username)
            if not res.get("ok"):
                error = res.get("error", "Could not create account.")
            elif res.get("needs_confirmation"):
                info_message = res.get("message")
            else:
                u = res["user"]
                session["sb_user"] = u
                session["sb_access_token"] = res["access_token"]
                session["sb_refresh_token"] = res.get("refresh_token")
                login_user(SupabaseSessionUser(u["id"], u["username"], u["email"], u.get("role", "user")))
                next_url = request.args.get("next") or request.form.get("next")
                return redirect(next_url if _is_safe_redirect_url(next_url) else url_for("reviews_page"))
        elif User.query.filter(func.lower(User.username) == username.lower()).first():
            error = "That username is already taken."
        elif User.query.filter(func.lower(User.email) == email).first():
            error = "An account with this email already exists."
        else:
            user = User(username=username, email=email, role="user")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            next_url = request.args.get("next") or request.form.get("next")
            return redirect(next_url if _is_safe_redirect_url(next_url) else url_for("reviews_page"))

    return render_template(
        "auth.html",
        mode="register",
        error=error,
        info_message=info_message,
        form_values=form_values,
        next_url=request.args.get("next", ""),
    )


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("reviews_page"))

    error = None
    identifier = ""
    if request.method == "POST":
        identifier = str(request.form.get("identifier", "") or request.form.get("email", "")).strip()
        password = str(request.form.get("password", ""))
        remember = bool(request.form.get("remember"))

        if not identifier or not password:
            error = "Enter your email and password." if is_supabase_enabled() else "Enter your email or username and password."
        elif is_supabase_enabled():
            res = supabase_login(email=identifier.lower(), password=password)
            if not res.get("ok"):
                error = res.get("error", "Invalid email or password.")
            else:
                u = res["user"]
                session["sb_user"] = u
                session["sb_access_token"] = res["access_token"]
                session["sb_refresh_token"] = res.get("refresh_token")
                login_user(
                    SupabaseSessionUser(u["id"], u["username"], u["email"], u.get("role", "user")),
                    remember=remember,
                )
                next_url = request.args.get("next") or request.form.get("next")
                return redirect(next_url if _is_safe_redirect_url(next_url) else url_for("reviews_page"))
        else:
            lowered = identifier.lower()
            user = User.query.filter(
                (func.lower(User.email) == lowered) | (func.lower(User.username) == lowered)
            ).first()
            if user is None or not user.check_password(password):
                error = "Invalid username/email or password."
            else:
                login_user(user, remember=remember)
                next_url = request.args.get("next") or request.form.get("next")
                return redirect(next_url if _is_safe_redirect_url(next_url) else url_for("reviews_page"))

    return render_template(
        "auth.html",
        mode="login",
        error=error,
        info_message=None,
        form_values={"identifier": identifier},
        next_url=request.args.get("next", ""),
    )


@app.route("/login/google")
def login_google():
    if current_user.is_authenticated:
        return redirect(url_for("reviews_page"))
    client = _get_google_oauth_client()
    if client is None:
        return render_template(
            "auth.html",
            mode="login",
            error=(
                "Google OAuth is not configured yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to your .env file "
                "(Authorized Redirect URI: http://127.0.0.1:5000/login/google/callback) and restart Flask — or sign in instantly with Gmail OTP below!"
            ),
            info_message=None,
            form_values={"identifier": ""},
            next_url=request.args.get("next", ""),
        )
    next_url = request.args.get("next", "")
    if _is_safe_redirect_url(next_url):
        session["oauth_next"] = next_url
    redirect_uri = url_for("google_auth_callback", _external=True)
    return client.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def google_auth_callback():
    client = _get_google_oauth_client()
    if client is None:
        flash("Google OAuth is not configured in .env.", "error")
        return redirect(url_for("login_page"))
    try:
        token = client.authorize_access_token()
        userinfo = token.get("userinfo")
        if not userinfo:
            userinfo = client.userinfo()
    except Exception as exc:
        LOGGER.exception("Google OAuth callback failed.")
        return render_template(
            "auth.html",
            mode="login",
            error=f"Google Sign-In failed ({exc}). Please try again or use Gmail OTP.",
            info_message=None,
            form_values={"identifier": ""},
            next_url="",
        )

    email = str((userinfo or {}).get("email", "")).strip().lower()
    google_id = str((userinfo or {}).get("sub", "")).strip() or None
    full_name = str((userinfo or {}).get("name", "")).strip() or None
    avatar_url = str((userinfo or {}).get("picture", "")).strip() or None
    if not email:
        return render_template(
            "auth.html",
            mode="login",
            error="Google did not return an email address for this account.",
            info_message=None,
            form_values={"identifier": ""},
            next_url="",
        )

    user = get_or_create_oauth_or_otp_user(
        email=email,
        username_hint=full_name,
        google_id=google_id,
        avatar_url=avatar_url,
    )
    login_user(user, remember=True)
    next_url = session.pop("oauth_next", None)
    return redirect(next_url if _is_safe_redirect_url(next_url) else url_for("reviews_page"))


@app.route("/api/auth/otp/send", methods=["POST"])
def api_auth_otp_send():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object with an email address."}), 400
    email = str(payload.get("email", "")).strip().lower()
    if not EMAIL_PATTERN.match(email):
        return jsonify({"error": "Please enter a valid Gmail or email address."}), 400

    code = create_otp_code(email, ttl_minutes=5)
    ok, delivery, message = send_otp_email(email, code, ttl_minutes=5)
    if not ok:
        return jsonify({"error": message, "delivery": delivery}), 502

    is_local_dev = request.remote_addr in {"127.0.0.1", "::1"} or request.host.startswith(("127.0.0.1", "localhost"))
    response_body = {
        "status": "sent",
        "email": email,
        "delivery": delivery,
        "message": message,
        "expires_in_seconds": 300,
    }
    if delivery == "console_dev" and is_local_dev:
        response_body["dev_otp"] = code
    return jsonify(response_body), 200


@app.route("/api/auth/otp/verify", methods=["POST"])
def api_auth_otp_verify():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object with email and 6-digit otp."}), 400
    email = str(payload.get("email", "")).strip().lower()
    raw_otp = str(payload.get("otp", "")).strip()
    next_url = str(payload.get("next", "")).strip()

    if not EMAIL_PATTERN.match(email):
        return jsonify({"error": "Please enter a valid email address."}), 400

    ok, message = verify_otp_code(email, raw_otp)
    if not ok:
        return jsonify({"error": message}), 400

    user = get_or_create_oauth_or_otp_user(email=email)
    login_user(user, remember=True)
    target_redirect = next_url if _is_safe_redirect_url(next_url) else url_for("reviews_page")
    return jsonify({
        "status": "ok",
        "message": "Signed in with verified email OTP.",
        "user": user.to_public_dict(),
        "redirect": target_redirect,
    }), 200


@app.route("/api/auth/status")
def api_auth_status():
    return jsonify({
        "authenticated": bool(current_user.is_authenticated),
        "google_oauth_configured": is_google_oauth_configured(),
        "gmail_smtp_configured": is_gmail_smtp_configured(),
        "user": (
            current_user.to_public_dict()
            if current_user.is_authenticated and hasattr(current_user, "to_public_dict")
            else (
                {
                    "id": current_user.id,
                    "username": current_user.username,
                    "email": getattr(current_user, "email", ""),
                    "role": getattr(current_user, "role", "user"),
                }
                if current_user.is_authenticated
                else None
            )
        ),
    })


@app.route("/logout", methods=["GET", "POST"])
def logout_page():
    if is_supabase_enabled():
        supabase_logout(session.get("sb_access_token"))
        session.pop("sb_user", None)
        session.pop("sb_access_token", None)
        session.pop("sb_refresh_token", None)
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for("analytics_page"))


@app.route("/reviews", methods=["GET", "POST"])
def reviews_page():
    if request.method == "POST":
        if not current_user.is_authenticated:
            return redirect(url_for("login_page", next=url_for("reviews_page")))
        comment = str(request.form.get("comment", "")).strip()
        raw_rating = request.form.get("rating", "")
        raw_agent = request.form.get("agent_name", "")
        target_type = str(request.form.get("target_type", "website")).strip().lower()
        agent_name, agent_error = (
            _canonical_agent_or_none(raw_agent) if target_type == "agent" else (None, None)
        )
        try:
            rating = int(raw_rating)
        except (TypeError, ValueError):
            rating = 0

        if agent_error:
            flash(agent_error, "error")
        elif not 1 <= rating <= 5:
            flash("Rating must be between 1 and 5 stars.", "error")
        elif len(comment) < 5 or len(comment) > 2000:
            flash("Review comment must be between 5 and 2,000 characters.", "error")
        else:
            sentiment = classify_review_sentiment(comment, rating)
            if is_supabase_enabled():
                status_code, resp = _call_supabase_with_refresh(
                    lambda tok: create_supabase_review(
                        access_token=tok,
                        user_id=str(current_user.id),
                        username=current_user.username,
                        author_role=current_user.role,
                        agent_name=agent_name,
                        rating=rating,
                        sentiment_label=sentiment,
                        comment=comment,
                    )
                )
                if status_code in (200, 201):
                    flash("Your review has been published to Supabase!", "success")
                else:
                    flash(resp.get("error", "Could not publish review."), "error")
            else:
                db.session.add(
                    Review(
                        user_id=current_user.id,
                        target_type="Agent" if agent_name else "Website",
                        agent_name=agent_name,
                        rating=rating,
                        sentiment_label=sentiment,
                        comment=comment,
                    )
                )
                db.session.commit()
                flash("Your review has been published!", "success")
        return redirect(url_for("reviews_page"))

    return render_template(
        "dashboard.html",
        active_page="reviews",
        mine_only=(request.args.get("mine") == "1"),
    )


@app.route("/api/reviews", methods=["GET", "POST"])
def api_reviews():
    if request.method == "POST":
        if not current_user.is_authenticated:
            return jsonify({"error": "Please log in to submit a review."}), 401
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Send a JSON object with rating, comment, and optional agent_name."}), 400

        comment = str(payload.get("comment", "")).strip()
        try:
            rating = int(payload.get("rating"))
        except (TypeError, ValueError):
            return jsonify({"error": "Rating must be an integer between 1 and 5."}), 400

        if not 1 <= rating <= 5:
            return jsonify({"error": "Rating must be between 1 and 5 stars."}), 400
        if len(comment) < 5 or len(comment) > 2000:
            return jsonify({"error": "Review comment must be between 5 and 2,000 characters."}), 400

        raw_agent = payload.get("agent_name")
        agent_name, agent_error = _canonical_agent_or_none(raw_agent)
        if agent_error:
            return jsonify({"error": agent_error}), 400

        sentiment = classify_review_sentiment(comment, rating)
        if is_supabase_enabled():
            status_code, resp = _call_supabase_with_refresh(
                lambda tok: create_supabase_review(
                    access_token=tok,
                    user_id=str(current_user.id),
                    username=current_user.username,
                    author_role=current_user.role,
                    agent_name=agent_name,
                    rating=rating,
                    sentiment_label=sentiment,
                    comment=comment,
                )
            )
            return jsonify(resp), status_code

        review = Review(
            user_id=current_user.id,
            target_type="Agent" if agent_name else "Website",
            agent_name=agent_name,
            rating=rating,
            sentiment_label=sentiment,
            comment=comment,
        )
        db.session.add(review)
        db.session.commit()
        all_reviews = Review.query.all()
        return jsonify({
            "review": review.to_dict(
                current_user_id=current_user.id,
                is_admin=(current_user.role == "admin"),
            ),
            "summary": _build_reviews_summary(all_reviews),
        }), 201

    # GET /api/reviews
    category = str(request.args.get("category", "all")).strip().lower()
    agent_filter = str(request.args.get("agent", "")).strip()
    sort_by = str(request.args.get("sort", "newest")).strip().lower()
    mine = str(request.args.get("mine", "")).strip().lower() in {"1", "true", "yes"}

    canonical_filter = None
    if agent_filter and agent_filter.lower() != "all":
        canonical, err = _canonical_agent_or_none(agent_filter)
        if not err and canonical:
            canonical_filter = canonical

    if mine and not current_user.is_authenticated:
        return jsonify({"error": "Log in to filter your own reviews."}), 401

    if is_supabase_enabled():
        uid = str(current_user.id) if current_user.is_authenticated else None
        is_admin = bool(current_user.is_authenticated and current_user.role == "admin")
        status_code, resp = list_supabase_reviews(
            category=category,
            agent=canonical_filter,
            sort_by=sort_by,
            mine_user_id=uid if mine else None,
            current_user_id=uid,
            is_admin=is_admin,
        )
        return jsonify(resp), status_code

    query = Review.query
    if category == "website":
        query = query.filter(Review.agent_name.is_(None))
    elif category == "agent":
        query = query.filter(Review.agent_name.isnot(None))

    if canonical_filter:
        query = query.filter(Review.agent_name == canonical_filter)

    if mine:
        query = query.filter(Review.user_id == current_user.id)

    if sort_by == "highest":
        query = query.order_by(Review.rating.desc(), Review.created_at.desc())
    elif sort_by == "lowest":
        query = query.order_by(Review.rating.asc(), Review.created_at.desc())
    else:
        query = query.order_by(Review.created_at.desc(), Review.id.desc())

    reviews = query.all()
    all_reviews = Review.query.all()
    uid = current_user.id if current_user.is_authenticated else None
    is_admin = bool(current_user.is_authenticated and current_user.role == "admin")
    return jsonify({
        "backend": "sqlite",
        "summary": _build_reviews_summary(all_reviews),
        "filtered_count": len(reviews),
        "reviews": [r.to_dict(current_user_id=uid, is_admin=is_admin) for r in reviews],
    })


@app.route("/api/reviews/<int:review_id>", methods=["PUT", "PATCH", "DELETE"])
@login_required
def api_review_item(review_id: int):
    is_admin = current_user.role == "admin"
    if is_supabase_enabled():
        if request.method == "DELETE":
            status_code, resp = _call_supabase_with_refresh(
                lambda tok: delete_supabase_review(access_token=tok, review_id=review_id)
            )
            return jsonify(resp), status_code

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Send a JSON object with updated fields."}), 400
        fields: dict = {}
        rating_val = None
        comment_val = None
        if "rating" in payload:
            try:
                rating_val = int(payload["rating"])
            except (TypeError, ValueError):
                return jsonify({"error": "Rating must be an integer between 1 and 5."}), 400
            if not 1 <= rating_val <= 5:
                return jsonify({"error": "Rating must be between 1 and 5 stars."}), 400
            fields["rating"] = rating_val
        if "comment" in payload:
            comment_val = str(payload["comment"]).strip()
            if len(comment_val) < 5 or len(comment_val) > 2000:
                return jsonify({"error": "Review comment must be between 5 and 2,000 characters."}), 400
            fields["comment"] = comment_val
        if "agent_name" in payload:
            agent_name, agent_error = _canonical_agent_or_none(payload.get("agent_name"))
            if agent_error:
                return jsonify({"error": agent_error}), 400
            fields["agent_name"] = agent_name
        if rating_val is not None or comment_val is not None:
            fields["sentiment_label"] = classify_review_sentiment(
                comment_val or "", rating_val if rating_val is not None else 3,
            )
        status_code, resp = _call_supabase_with_refresh(
            lambda tok: update_supabase_review(
                access_token=tok,
                review_id=review_id,
                user_id=str(current_user.id),
                is_admin=is_admin,
                fields=fields,
            )
        )
        return jsonify(resp), status_code

    review = db.session.get(Review, review_id)
    if review is None:
        return jsonify({"error": "Review not found."}), 404

    if review.user_id != current_user.id and not is_admin:
        return jsonify({"error": "You can only modify your own reviews."}), 403

    if request.method == "DELETE":
        db.session.delete(review)
        db.session.commit()
        return jsonify({
            "deleted": review_id,
            "summary": _build_reviews_summary(Review.query.all()),
        })

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object with updated fields."}), 400

    if "rating" in payload:
        try:
            rating = int(payload["rating"])
        except (TypeError, ValueError):
            return jsonify({"error": "Rating must be an integer between 1 and 5."}), 400
        if not 1 <= rating <= 5:
            return jsonify({"error": "Rating must be between 1 and 5 stars."}), 400
        review.rating = rating

    if "comment" in payload:
        comment = str(payload["comment"]).strip()
        if len(comment) < 5 or len(comment) > 2000:
            return jsonify({"error": "Review comment must be between 5 and 2,000 characters."}), 400
        review.comment = comment

    if "agent_name" in payload:
        agent_name, agent_error = _canonical_agent_or_none(payload.get("agent_name"))
        if agent_error:
            return jsonify({"error": agent_error}), 400
        review.agent_name = agent_name
        review.target_type = "Agent" if agent_name else "Website"

    review.sentiment_label = classify_review_sentiment(review.comment, review.rating)
    review.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({
        "review": review.to_dict(current_user_id=current_user.id, is_admin=is_admin),
        "summary": _build_reviews_summary(Review.query.all()),
    })


@app.route("/predict", methods=["POST"])
@app.route("/api/sentiment/analyze", methods=["POST"])
def predict():
    # Validate and normalize input before loading or invoking prediction models.
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object containing a review string."}), 400
    review = payload.get("review", "")
    if not isinstance(review, str):
        return jsonify({"error": "The review must be text."}), 400
    if len(review) > MAX_REVIEW_LENGTH:
        message = f"Reviews must be {MAX_REVIEW_LENGTH} characters or fewer."
        return jsonify({"error": message}), 400

    cleaned_review = clean_review(review)
    if not cleaned_review:
        return jsonify({"error": "Please enter a valid review before predicting."}), 400

    assets = load_assets()
    if not assets.get("available_models"):
        message = (
            "No trained sentiment models could be loaded. Run train_models.py "
            "and check that model files were generated."
        )
        return jsonify({"error": message}), 503

    try:
        prediction = predict_single_review(review, assets)
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503

    analysis = enrich_review_context(review)
    overall = prediction.get("overall", {})
    derived_score = float(overall.get("derived_score", 5.5))
    predicted_label = str(overall.get("label", "Neutral"))
    detected_agents = [item["agent"] for item in analysis.get("agents", [])]
    detected_maps = [item["map"] for item in analysis.get("maps", [])]

    # Optionally record into live SQLite telemetry so /sentiment counters update in real time.
    recorded_live = False
    if bool(payload.get("record_live", False)):
        try:
            record_analyzed_review(
                review_text=review,
                sentiment_label=predicted_label,
                derived_score=derived_score,
                agents=detected_agents,
                maps=detected_maps,
            )
            recorded_live = True
        except Exception:
            LOGGER.exception("Could not record live analyzed review.")

    # Build Community Comparison against the 100,000+ (2020-2026) corpus for detected agents & maps
    community_comparison = []
    try:
        dist = get_sentiment_distribution()
        overall_avg = float(dist.get("average_score") or 6.1)
        community_comparison.append({
            "entity": "All VALORANT Reviews",
            "entity_type": "overall",
            "community_avg_score": round(overall_avg, 2),
            "review_score": round(derived_score, 1),
            "delta": round(derived_score - overall_avg, 2),
            "positive_percentage": dist["percentages"]["Positive"],
            "total_mentions": dist["total_reviews"],
        })
        for agent_name in detected_agents:
            a_stats = get_agent_review_sentiment(agent_name)
            if a_stats and a_stats.get("total_mentions"):
                c_avg = float(a_stats.get("average_score") or overall_avg)
                community_comparison.append({
                    "entity": agent_name,
                    "entity_type": "agent",
                    "community_avg_score": round(c_avg, 2),
                    "review_score": round(derived_score, 1),
                    "delta": round(derived_score - c_avg, 2),
                    "positive_percentage": a_stats["positive_percentage"],
                    "total_mentions": a_stats["total_mentions"],
                })
        map_summary = get_map_sentiment_summary()
        for map_name in detected_maps:
            m_stats = map_summary.get(map_name)
            if m_stats and m_stats.get("total_mentions"):
                c_avg = float(m_stats.get("average_score") or overall_avg)
                community_comparison.append({
                    "entity": map_name,
                    "entity_type": "map",
                    "community_avg_score": round(c_avg, 2),
                    "review_score": round(derived_score, 1),
                    "delta": round(derived_score - c_avg, 2),
                    "positive_percentage": m_stats["positive_percentage"],
                    "total_mentions": m_stats["total_mentions"],
                })
    except Exception:
        LOGGER.exception("Could not compute community comparison.")

    return jsonify({
        **prediction,
        "analysis": analysis,
        "community_comparison": community_comparison,
        "recorded_live": recorded_live,
    })


def _extract_reviews_from_csv(raw_bytes: bytes, filename: str = "") -> list[str]:
    text = raw_bytes.decode("utf-8-sig", errors="replace").strip()
    if not text:
        return []
    if filename.lower().endswith(".txt"):
        return [line.strip() for line in text.splitlines() if line.strip()]

    known_headers = {"review_text", "review", "text", "comment", "feedback", "body", "message"}
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []

    first_row = [str(cell).strip() for cell in rows[0]]
    lowered_header = [cell.casefold() for cell in first_row]
    header_match_idx = next(
        (idx for idx, col in enumerate(lowered_header) if col in known_headers),
        None,
    )
    if header_match_idx is not None:
        return [
            str(r[header_match_idx]).strip()
            for r in rows[1:]
            if len(r) > header_match_idx and str(r[header_match_idx]).strip()
        ]
    if len(first_row) > 1:
        # Multi-column CSV with non-standard header: pick column with longest average text
        data_rows = rows[1:] if rows[1:] else rows
        col_scores = []
        for col_idx in range(len(first_row)):
            vals = [str(r[col_idx]).strip() for r in data_rows[:50] if len(r) > col_idx]
            avg_len = sum(len(v) for v in vals) / max(len(vals), 1)
            col_scores.append((avg_len, col_idx))
        best_col = max(col_scores)[1]
        return [
            str(r[best_col]).strip()
            for r in data_rows
            if len(r) > best_col and str(r[best_col]).strip()
        ]
    # Single-column file without a recognized header: treat every line as a review!
    return [str(r[0]).strip() for r in rows if r and str(r[0]).strip()]


@app.route("/api/sentiment/batch", methods=["POST"])
def api_sentiment_batch():
    reviews: list[str] = []
    include_distilbert = False

    if "file" in request.files:
        uploaded = request.files["file"]
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "Upload a non-empty CSV or text file."}), 400
        raw_bytes = uploaded.read()
        if not raw_bytes:
            return jsonify({"error": "Uploaded file is empty."}), 400
        reviews = _extract_reviews_from_csv(raw_bytes, uploaded.filename)
        include_distilbert = str(request.form.get("include_distilbert", "false")).casefold() in {"1", "true", "yes"}
    else:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("reviews"), list):
            return jsonify({"error": "Send a JSON object with a 'reviews' list or upload a CSV file."}), 400
        if not all(isinstance(item, str) for item in payload["reviews"]):
            return jsonify({"error": "Every item in 'reviews' must be a text string."}), 400
        reviews = payload["reviews"]
        include_distilbert = bool(payload.get("include_distilbert", False))

    if not reviews:
        return jsonify({"error": "Provide at least one review for batch analysis."}), 400
    if any(len(item) > MAX_REVIEW_LENGTH for item in reviews[:MAX_BATCH_REVIEWS]):
        return jsonify({"error": f"Each review must be {MAX_REVIEW_LENGTH} characters or fewer."}), 400

    assets = load_assets()
    if not assets.get("available_models"):
        return jsonify({"error": "No trained sentiment models are loaded."}), 503

    try:
        report = analyze_reviews_batch(reviews, assets, include_distilbert=include_distilbert)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503

    return jsonify(report)


@app.route("/api/match/predict", methods=["POST"])
def api_match_predict():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object with map, team1, and team2 agent lists."}), 400

    map_name = str(payload.get("map", "") or "").strip()
    team1 = payload.get("team1")
    team2 = payload.get("team2")
    patch = payload.get("patch")

    if not map_name:
        return jsonify({"error": "Map name is required."}), 400
    if not isinstance(team1, list) or not isinstance(team2, list):
        return jsonify({"error": "Both team1 and team2 must be lists of 5 agent names."}), 400

    try:
        result = predict_match_draft(map_name, team1, team2, patch=patch)
    except FileNotFoundError as error:
        return jsonify({"error": str(error)}), 503

    if result["status"] == "unknown_map":
        return jsonify({"error": f"Unknown map: {map_name}"}), 404
    if result["status"] == "invalid_lineup":
        return jsonify({"error": result.get("error", "Invalid team lineup.")}), 400
    return jsonify(result)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "project": "VALOSENT AI"})


@app.route("/api/assets")
def api_assets():
    response = jsonify(get_all_assets())
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@app.route("/api/maps")
def api_maps():
    return jsonify({"maps": get_maps()})


@app.route("/api/dashboard-summary")
def api_dashboard_summary():
    return jsonify(get_dataset_summary())


@app.route("/api/sentiment-distribution")
@app.route("/api/sentiment/distribution")
def api_sentiment_distribution():
    try:
        return jsonify(get_sentiment_distribution())
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 503


@app.route("/api/sentiment/scores")
def api_sentiment_scores():
    try:
        return jsonify(get_score_distribution())
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 503


@app.route("/api/sentiment/by-agent")
def api_sentiment_by_agent():
    try:
        agents = [item for item in get_sentiment_by_agent() if item["total_mentions"]]
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 503
    return jsonify({
        "agents": agents,
        "method": "Formal mention-level polarity scoring with local clause windows, negation handling, and weighted evidence aggregation.",
    })


@app.route("/api/agents")
def api_agents():
    return jsonify({"agents": get_agents()})


@app.route("/api/agent-catalog")
def api_agent_catalog():
    try:
        historical_agents = {normalize_name(item["agent"]) for item in get_agents()}
    except FileNotFoundError:
        historical_agents = set()
    try:
        agents = get_agent_catalog()
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 503
    return jsonify({
        "agents": [
            {**item, "has_match_data": normalize_name(item["agent"]) in historical_agents}
            for item in agents
        ]
    })


@app.route("/api/agents/<path:agent_name>")
def api_agent_profile(agent_name: str):
    normalized_name = normalize_name(agent_name)
    try:
        catalog_entry = next(
            (item for item in get_agent_catalog() if normalize_name(item["agent"]) == normalized_name),
            None,
        )
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 503
    if catalog_entry is None:
        return jsonify({"error": f"Unknown agent: {agent_name}"}), 404

    try:
        historical = get_agent_stats(catalog_entry["agent"])
    except FileNotFoundError:
        historical = None
    try:
        sentiment = get_agent_review_sentiment(catalog_entry["agent"])
    except (FileNotFoundError, ValueError):
        sentiment = None
    maps = historical["maps"] if historical else []
    qualified_maps = [item for item in maps if item["resolved_maps"] >= 20]
    best_maps = sorted(qualified_maps, key=lambda item: item["win_rate_lower_bound"], reverse=True)[:3]
    worst_maps = sorted(qualified_maps, key=lambda item: item["win_rate_lower_bound"])[:3]
    return jsonify({
        "agent": catalog_entry["agent"],
        "role": catalog_entry["role"],
        "description": None,
        "has_match_data": historical is not None,
        "historical": historical,
        "best_maps": best_maps,
        "worst_maps": worst_maps,
        "review_sentiment": sentiment,
        "assets": get_agent_asset(catalog_entry["agent"], catalog_entry["role"]),
    })


@app.route("/api/roles")
def api_roles():
    return jsonify({"roles": get_roles()})


@app.route("/api/map/<map_name>")
@app.route("/api/maps/<map_name>")
def api_map(map_name: str):
    result = get_map_stats(map_name)
    if result is None:
        return jsonify({"error": f"Unknown map: {map_name}"}), 404
    return jsonify({**result, "assets": get_map_asset(result["map"])})


@app.route("/api/agent/<path:agent_name>")
def api_agent(agent_name: str):
    result = get_agent_stats(agent_name)
    if result is None:
        return jsonify({"error": f"Unknown agent: {agent_name}"}), 404
    return jsonify(result)


@app.route("/api/agent-stats")
def api_agent_stats():
    agent_name = request.args.get("agent", "")
    result = get_agent_stats(agent_name)
    if result is None:
        return jsonify({"error": f"Unknown agent: {agent_name}"}), 404
    return jsonify(result)


@app.route("/api/recommend")
def api_recommend():
    map_name = request.args.get("map", "")
    result = get_best_agents_for_map(
        map_name,
        side=request.args.get("side", "both"),
        role=request.args.get("role"),
    )
    status_code = 404 if result["status"] == "unknown_map" else 200
    if result["status"] == "invalid_side":
        status_code = 400
    return jsonify(result), status_code


@app.route("/api/recommend/attack")
def api_recommend_attack():
    result = get_best_agents_for_map(
        request.args.get("map", ""),
        side="attack",
        role=request.args.get("role"),
    )
    status_code = 404 if result["status"] == "unknown_map" else 200
    return jsonify(result), status_code


@app.route("/api/recommend/defense")
def api_recommend_defense():
    result = get_best_agents_for_map(
        request.args.get("map", ""),
        side="defense",
        role=request.args.get("role"),
    )
    status_code = 404 if result["status"] == "unknown_map" else 200
    return jsonify(result), status_code


@app.route("/api/team-composition")
def api_team_composition():
    map_name = request.args.get("map", "")
    result = get_best_team_compositions(map_name)
    status_code = 404 if result["status"] == "unknown_map" else 200
    return jsonify(result), status_code


@app.route("/api/agent-synergy")
def api_agent_pairings():
    agent_name = request.args.get("agent", "")
    if not agent_name:
        return jsonify({"error": "The agent query parameter is required."}), 400
    result = get_agent_synergy(agent_name, map_name=request.args.get("map"))
    status_code = 404 if result["status"] == "unknown_agent" else 200
    return jsonify(result), status_code


@app.route("/api/agent-map-stats")
def api_agent_map_stats():
    map_name = request.args.get("map")
    if map_name and map_name.casefold() != "all" and not any(
        value.casefold() == map_name.casefold() for value in get_maps()
    ):
        return jsonify({"error": f"Unknown map: {map_name}"}), 404
    return jsonify({
        "map": map_name or "All",
        "role": request.args.get("role", "All"),
        "stats": get_map_agent_stats(
            map_name=request.args.get("map"),
            role=request.args.get("role"),
        ),
    })


@app.route("/api/agent-map-performance")
def api_agent_map_performance():
    map_name = request.args.get("map")
    agent_name = request.args.get("agent")
    role = request.args.get("role", "All")
    side = request.args.get("side", "both").casefold()
    if side not in {"both", "attack", "defense"}:
        return jsonify({"error": f"Unknown side: {side}"}), 400

    try:
        maps = get_maps()
        agents = get_agents()
    except FileNotFoundError as error:
        return jsonify({"error": str(error)}), 503

    canonical_map = None
    if map_name and map_name.casefold() != "all":
        canonical_map = next((value for value in maps if value.casefold() == map_name.casefold()), None)
        if canonical_map is None:
            return jsonify({"error": f"Unknown map: {map_name}"}), 404

    canonical_agent = None
    if agent_name:
        canonical_agent = next(
            (item["agent"] for item in agents if normalize_name(item["agent"]) == normalize_name(agent_name)),
            None,
        )
        if canonical_agent is None:
            return jsonify({"error": f"Unknown agent: {agent_name}"}), 404

    stats = get_map_agent_stats(canonical_map, role)
    if canonical_agent:
        stats = [item for item in stats if normalize_name(item["agent_name"]) == normalize_name(canonical_agent)]

    if side == "attack":
        stats.sort(key=lambda item: item["attack_acs_median"] if item["attack_acs_median"] is not None else float("-inf"), reverse=True)
        ranking_metric = "median T-side ACS"
    elif side == "defense":
        stats.sort(key=lambda item: item["defense_acs_median"] if item["defense_acs_median"] is not None else float("-inf"), reverse=True)
        ranking_metric = "median CT-side ACS"
    else:
        stats.sort(key=lambda item: item["appearances"], reverse=True)
        ranking_metric = "historical appearances"

    return jsonify({
        "map": canonical_map or "All",
        "agent": canonical_agent or "All",
        "role": role,
        "side": side,
        "ranking_metric": ranking_metric,
        "stats": stats,
    })


@app.route("/api/agent-comparison")
def api_agent_comparison():
    requested_agents = request.args.getlist("agent")
    if len(requested_agents) == 1 and "," in requested_agents[0]:
        requested_agents = [value.strip() for value in requested_agents[0].split(",") if value.strip()]
    if len(requested_agents) < 2 or len(requested_agents) > 5:
        return jsonify({"error": "Provide between two and five agent names."}), 400
    known_agents = {normalize_name(item["agent"]) for item in get_agents()}
    unknown_agents = [name for name in requested_agents if normalize_name(name) not in known_agents]
    if unknown_agents:
        return jsonify({"error": f"Unknown agents: {', '.join(unknown_agents)}"}), 404
    map_name = request.args.get("map")
    if map_name and map_name.casefold() != "all" and not any(
        value.casefold() == map_name.casefold() for value in get_maps()
    ):
        return jsonify({"error": f"Unknown map: {map_name}"}), 404
    summary = get_agent_comparison_summary(requested_agents, map_name)
    for profile in summary["profiles"]:
        try:
            sent = get_agent_review_sentiment(profile["agent"])
        except (FileNotFoundError, ValueError):
            sent = None
        profile["sentiment"] = sent

    def _pick_winner(metric_getter, label):
        valid = [(p["agent"], metric_getter(p)) for p in summary["profiles"]]
        valid = [(a, v) for a, v in valid if v is not None]
        if not valid:
            return None
        winner_agent, winner_val = max(valid, key=lambda item: item[1])
        return {"metric": label, "winner": winner_agent, "value": winner_val}

    advantages = [
        item for item in (
            _pick_winner(lambda p: p["map_win_rate"], "Map Win Rate"),
            _pick_winner(lambda p: p["pick_rate"], "Pick Rate"),
            _pick_winner(lambda p: p["attack_acs_median"], "Attack (T) Median ACS"),
            _pick_winner(lambda p: p["defense_acs_median"], "Defense (CT) Median ACS"),
            _pick_winner(
                lambda p: (p["sentiment"]["positive_percentage"] / 100.0)
                if p.get("sentiment") and p["sentiment"].get("total_mentions")
                else None,
                "Positive Sentiment",
            ),
        )
        if item is not None
    ]

    return jsonify({
        "map": map_name or "All",
        "agents": [p["agent"] for p in summary["profiles"]],
        "profiles": summary["profiles"],
        "advantages": advantages,
        "pair_synergies": summary["pair_synergies"],
        "stats": get_agent_comparison(requested_agents, map_name),
    })


@app.route("/api/model-comparison")
def api_model_comparison():
    evaluation_path = BASE_DIR / "results" / "model_evaluation.json"
    if not evaluation_path.exists():
        return jsonify({"error": "Model evaluation results are not available yet."}), 404
    try:
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        LOGGER.exception("Could not read the saved sentiment model evaluation.")
        return jsonify({"error": "Saved model evaluation results are invalid or unreadable."}), 503
    if not isinstance(evaluation, dict) or not isinstance(evaluation.get("models"), dict):
        return jsonify({"error": "Saved model evaluation results have an unexpected format."}), 503
    return jsonify(evaluation)


@app.route("/api/match-model-results")
def api_match_model_results():
    evaluation_path = BASE_DIR / "results" / "match_model_evaluation.json"
    if not evaluation_path.exists():
        return jsonify({"error": "Match outcome model results are not available yet."}), 404
    return jsonify(json.loads(evaluation_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=False, host="0.0.0.0", port=port)
