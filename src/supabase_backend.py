"""Supabase Auth + PostgREST client for VALOSENT AI persistent cloud accounts and reviews."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"
LOGGER = logging.getLogger(__name__)

_ENV_LOADED = False
_AGENT_REVIEWS_CACHE: tuple[float, list[dict]] | None = None
_AGENT_REVIEWS_TTL_SECONDS = 5.0


def _load_dotenv_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_supabase_config() -> tuple[str, str]:
    _load_dotenv_once()
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.environ.get("SUPABASE_ANON_KEY", "").strip()
    )
    return url, key


def is_supabase_enabled() -> bool:
    _load_dotenv_once()
    if os.environ.get("VALOSENT_USE_SQLITE", "").strip().lower() in {"1", "true", "yes"}:
        return False
    url, key = get_supabase_config()
    return bool(url and key)


def invalidate_agent_reviews_cache() -> None:
    global _AGENT_REVIEWS_CACHE
    _AGENT_REVIEWS_CACHE = None


def _supabase_request(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    access_token: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = 12,
) -> tuple[int, dict | list | None]:
    base_url, api_key = get_supabase_config()
    url = f"{base_url}{path}"
    headers = {
        "apikey": api_key,
        "Accept": "application/json",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw.strip() else {"error": str(exc)}
        except json.JSONDecodeError:
            body = {"error": raw or str(exc)}
        return exc.code, body
    except urllib.error.URLError as exc:
        LOGGER.warning("Supabase network error on %s %s: %s", method, path, exc)
        return 503, {"error": f"Could not reach Supabase: {exc.reason}"}


def _extract_error(body, default: str) -> str:
    if isinstance(body, dict):
        for key in ("msg", "error_description", "message", "error"):
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return default


def _ensure_profile(user_id: str, username: str, access_token: str) -> dict:
    # Check existing profile first
    q = urllib.parse.quote(user_id, safe="")
    status, data = _supabase_request(
        "GET",
        f"/rest/v1/valosent_profiles?id=eq.{q}&select=id,username,role,created_at",
        access_token=access_token,
    )
    if status == 200 and isinstance(data, list) and data:
        return data[0]

    clean_name = "".join(ch for ch in username if ch.isalnum() or ch == "_")[:28]
    if len(clean_name) < 3:
        clean_name = f"agent_{user_id[:6]}"

    for candidate in (clean_name, f"{clean_name[:22]}_{user_id[:5]}"):
        ins_status, ins_data = _supabase_request(
            "POST",
            "/rest/v1/valosent_profiles",
            payload={"id": user_id, "username": candidate, "role": "user"},
            access_token=access_token,
            extra_headers={"Prefer": "return=representation"},
        )
        if ins_status in (200, 201) and isinstance(ins_data, list) and ins_data:
            return ins_data[0]

    return {"id": user_id, "username": clean_name, "role": "user"}


def supabase_signup(email: str, password: str, username: str) -> dict:
    # Check username uniqueness before creating auth user
    q_name = urllib.parse.quote(username, safe="")
    chk_status, chk_data = _supabase_request(
        "GET",
        f"/rest/v1/valosent_profiles?username=ilike.{q_name}&select=id",
    )
    if chk_status == 200 and isinstance(chk_data, list) and chk_data:
        return {"ok": False, "error": "That username is already taken."}

    status, body = _supabase_request(
        "POST",
        "/auth/v1/signup",
        payload={
            "email": email,
            "password": password,
            "data": {"username": username, "full_name": username},
        },
    )
    if status not in (200, 201) or not isinstance(body, dict):
        return {"ok": False, "error": _extract_error(body, "Could not create Supabase account.")}

    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    user_obj = body.get("user") if isinstance(body.get("user"), dict) else body
    user_id = user_obj.get("id")

    if not access_token:
        return {
            "ok": True,
            "needs_confirmation": True,
            "message": "Account created in Supabase! Please confirm your email address, then log in.",
        }

    profile = _ensure_profile(str(user_id), username, access_token)
    return {
        "ok": True,
        "needs_confirmation": False,
        "user": {
            "id": str(user_id),
            "email": email,
            "username": profile.get("username", username),
            "role": profile.get("role", "user"),
        },
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


def supabase_login(email: str, password: str) -> dict:
    status, body = _supabase_request(
        "POST",
        "/auth/v1/token?grant_type=password",
        payload={"email": email, "password": password},
    )
    if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
        return {"ok": False, "error": _extract_error(body, "Invalid email or password.")}

    access_token = body["access_token"]
    refresh_token = body.get("refresh_token")
    user_obj = body.get("user", {})
    user_id = str(user_obj.get("id", ""))
    meta = user_obj.get("user_metadata") or {}
    fallback_name = meta.get("username") or email.split("@")[0]
    profile = _ensure_profile(user_id, str(fallback_name), access_token)

    return {
        "ok": True,
        "user": {
            "id": user_id,
            "email": user_obj.get("email", email),
            "username": profile.get("username", fallback_name),
            "role": profile.get("role", "user"),
        },
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


def supabase_refresh_session(refresh_token: str) -> dict | None:
    if not refresh_token:
        return None
    status, body = _supabase_request(
        "POST",
        "/auth/v1/token?grant_type=refresh_token",
        payload={"refresh_token": refresh_token},
    )
    if status == 200 and isinstance(body, dict) and body.get("access_token"):
        return {
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token", refresh_token),
        }
    return None


def supabase_logout(access_token: str | None) -> None:
    if access_token:
        _supabase_request("POST", "/auth/v1/logout", access_token=access_token)


def _format_review_row(row: dict, current_user_id: str | None = None, is_admin: bool = False) -> dict:
    owner_id = str(row.get("user_id")) if row.get("user_id") else None
    can_manage = bool(current_user_id and owner_id and (owner_id == str(current_user_id) or is_admin))
    agent_name = row.get("agent_name")
    return {
        "id": int(row["id"]),
        "user_id": owner_id,
        "username": row.get("author_username") or "Anonymous",
        "author_role": row.get("author_role") or "user",
        "agent_name": agent_name,
        "target_type": "agent" if agent_name else "website",
        "rating": int(row["rating"]),
        "sentiment_label": row.get("sentiment_label") or "Neutral",
        "comment": row.get("comment") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "can_edit": can_manage,
        "can_delete": can_manage,
    }


def _summarize_rows(rows: list[dict]) -> dict:
    total = len(rows)
    website_count = sum(1 for r in rows if not r.get("agent_name"))
    agent_count = total - website_count
    avg_rating = round(sum(int(r.get("rating", 0)) for r in rows) / total, 2) if total else 0.0
    pos_count = sum(1 for r in rows if r.get("sentiment_label") == "Positive")
    neu_count = sum(1 for r in rows if r.get("sentiment_label") == "Neutral")
    neg_count = sum(1 for r in rows if r.get("sentiment_label") == "Negative")
    unique_authors = len({r.get("author_username") for r in rows if r.get("author_username")})
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


def list_supabase_reviews(
    *,
    category: str = "all",
    agent: str | None = None,
    sort_by: str = "newest",
    mine_user_id: str | None = None,
    current_user_id: str | None = None,
    is_admin: bool = False,
) -> tuple[int, dict]:
    status, all_rows = _supabase_request(
        "GET",
        "/rest/v1/valosent_reviews?select=*&order=created_at.desc,id.desc",
    )
    if status != 200 or not isinstance(all_rows, list):
        return status, {"error": _extract_error(all_rows, "Could not fetch reviews from Supabase.")}

    filtered = list(all_rows)
    if category == "website":
        filtered = [r for r in filtered if not r.get("agent_name")]
    elif category == "agent":
        filtered = [r for r in filtered if r.get("agent_name")]

    if agent:
        filtered = [r for r in filtered if r.get("agent_name") == agent]

    if mine_user_id:
        filtered = [r for r in filtered if str(r.get("user_id") or "") == str(mine_user_id)]

    if sort_by == "highest":
        filtered.sort(key=lambda r: (int(r.get("rating", 0)), str(r.get("created_at") or "")), reverse=True)
    elif sort_by == "lowest":
        filtered.sort(key=lambda r: (int(r.get("rating", 0)), str(r.get("created_at") or "")))

    return 200, {
        "backend": "supabase",
        "summary": _summarize_rows(all_rows),
        "filtered_count": len(filtered),
        "reviews": [_format_review_row(r, current_user_id=current_user_id, is_admin=is_admin) for r in filtered],
    }


def create_supabase_review(
    *,
    access_token: str,
    user_id: str,
    username: str,
    author_role: str,
    agent_name: str | None,
    rating: int,
    sentiment_label: str,
    comment: str,
) -> tuple[int, dict]:
    status, data = _supabase_request(
        "POST",
        "/rest/v1/valosent_reviews",
        payload={
            "user_id": user_id,
            "author_username": username,
            "author_role": "user",
            "agent_name": agent_name,
            "rating": int(rating),
            "sentiment_label": sentiment_label,
            "comment": comment,
        },
        access_token=access_token,
        extra_headers={"Prefer": "return=representation"},
    )
    if status not in (200, 201) or not isinstance(data, list) or not data:
        return status, {"error": _extract_error(data, "Could not publish review to Supabase.")}

    invalidate_agent_reviews_cache()
    _, summary_resp = list_supabase_reviews(current_user_id=user_id, is_admin=(author_role == "admin"))
    return 201, {
        "review": _format_review_row(data[0], current_user_id=user_id, is_admin=(author_role == "admin")),
        "summary": summary_resp.get("summary"),
    }


def update_supabase_review(
    *,
    access_token: str,
    review_id: int,
    user_id: str,
    is_admin: bool,
    fields: dict,
) -> tuple[int, dict]:
    payload = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
    status, data = _supabase_request(
        "PATCH",
        f"/rest/v1/valosent_reviews?id=eq.{int(review_id)}",
        payload=payload,
        access_token=access_token,
        extra_headers={"Prefer": "return=representation"},
    )
    if status != 200 or not isinstance(data, list):
        return status, {"error": _extract_error(data, "Could not update review.")}
    if not data:
        return 403, {"error": "Review not found or you do not have permission to edit it."}

    invalidate_agent_reviews_cache()
    return 200, {"review": _format_review_row(data[0], current_user_id=user_id, is_admin=is_admin)}


def delete_supabase_review(*, access_token: str, review_id: int) -> tuple[int, dict]:
    status, data = _supabase_request(
        "DELETE",
        f"/rest/v1/valosent_reviews?id=eq.{int(review_id)}",
        access_token=access_token,
        extra_headers={"Prefer": "return=representation"},
    )
    if status != 200 or not isinstance(data, list):
        return status, {"error": _extract_error(data, "Could not delete review.")}
    if not data:
        return 403, {"error": "Review not found or you do not have permission to delete it."}

    invalidate_agent_reviews_cache()
    _, summary_resp = list_supabase_reviews()
    return 200, {"deleted": review_id, "summary": summary_resp.get("summary")}


def get_supabase_agent_review_rows() -> list[dict]:
    """Fetch persisted agent reviews from Supabase (short 5s TTL cache) for /agents & /sentiment."""
    global _AGENT_REVIEWS_CACHE
    if not is_supabase_enabled():
        return []
    now = time.monotonic()
    if _AGENT_REVIEWS_CACHE is not None and (now - _AGENT_REVIEWS_CACHE[0]) < _AGENT_REVIEWS_TTL_SECONDS:
        return _AGENT_REVIEWS_CACHE[1]

    status, data = _supabase_request(
        "GET",
        "/rest/v1/valosent_reviews?agent_name=not.is.null&select=agent_name,sentiment_label,created_at",
        timeout=6,
    )
    if status == 200 and isinstance(data, list):
        _AGENT_REVIEWS_CACHE = (now, data)
        return data
    return _AGENT_REVIEWS_CACHE[1] if _AGENT_REVIEWS_CACHE else []
