from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_DATA_PATH = BASE_DIR / "data" / "user_reviews.parquet"
REVIEW_DATA_PATH = DEFAULT_REVIEW_DATA_PATH
SUMMARY_CACHE_PATH = BASE_DIR / "data" / "review_summary_cache.json"
AGENT_ROLES_PATH = BASE_DIR / "data" / "agents" / "agent_roles.csv"
SENTIMENTS = ("Positive", "Neutral", "Negative")
POLARITY_WORDS = {
    "Positive": {
        "amazing": 3.0,
        "awesome": 2.5,
        "balanced": 2.0,
        "best": 2.5,
        "excellent": 3.0,
        "effective": 1.8,
        "enjoy": 1.6,
        "enjoyable": 1.8,
        "fun": 1.7,
        "good": 1.5,
        "great": 2.2,
        "helpful": 1.6,
        "love": 2.8,
        "like": 1.4,
        "powerful": 2.0,
        "solid": 1.5,
        "strong": 2.0,
        "useful": 1.8,
        "win": 1.8,
        "smooth": 1.3,
        "clutch": 1.5,
        "clean": 1.3,
        "op": 1.0,
    },
    "Negative": {
        "annoying": 2.0,
        "awful": 2.8,
        "bad": 1.8,
        "broken": 2.3,
        "buggy": 2.0,
        "frustrating": 2.4,
        "hate": 3.0,
        "terrible": 3.1,
        "weak": 2.2,
        "worse": 2.6,
        "worst": 3.2,
        "trash": 2.8,
        "cooked": 2.1,
        "poor": 1.8,
        "stuck": 1.2,
        "laggy": 1.8,
        "toxic": 1.8,
    },
}
NEGATIONS = re.compile(r"\b(?:not|never|no|isn't|aren't|wasn't|weren't|don't|doesn't|didn't|can't|cannot|won't|hardly|rarely)\b(?:\W+\w+){0,2}\W*$", re.IGNORECASE)
CLAUSE_BOUNDARY = re.compile(r"[,;.!?]|\b(?:but|however|although|though|yet)\b", re.IGNORECASE)
TOPIC_TERMS = {
    "Gameplay": ("gameplay", "gunplay", "ability", "abilities", "aim", "recoil", "movement", "shooting", "weapon", "weapons"),
    "Matchmaking": ("matchmaking", "match making"),
    "Patch": ("patch", "update", "nerf", "nerfed", "buff", "buffed"),
    "Performance": ("performance", "fps", "lag", "ping", "server", "hitreg", "hit registration", "frame rate"),
}
INTENSIFIERS = {
    "very": 1.2,
    "really": 1.2,
    "super": 1.3,
    "extremely": 1.5,
    "so": 1.2,
    "too": 1.1,
}
CONTRAST_WORDS = {"but", "however", "although", "though", "yet"}


@lru_cache(maxsize=1)
def _load_review_frame() -> pd.DataFrame:
    if not REVIEW_DATA_PATH.exists():
        raise FileNotFoundError(f"Review dataset not found: {REVIEW_DATA_PATH}")

    frame = pd.read_parquet(REVIEW_DATA_PATH)
    columns = {str(column).strip().casefold(): column for column in frame.columns}
    text_column = next((columns[name] for name in ("review_text", "review", "text") if name in columns), None)
    date_column = next((columns[name] for name in ("published_date", "date", "review_date") if name in columns), None)
    if text_column is None:
        raise ValueError("Review dataset must contain a review-text column.")

    return pd.DataFrame({
        "review_text": frame[text_column].fillna("").astype(str),
        "published_date": pd.to_datetime(frame[date_column], errors="coerce") if date_column else pd.NaT,
    })


@lru_cache(maxsize=1)
def get_agent_catalog() -> list[dict]:
    if not AGENT_ROLES_PATH.exists():
        raise FileNotFoundError(f"Agent role dataset not found: {AGENT_ROLES_PATH}")

    roles = pd.read_csv(AGENT_ROLES_PATH)
    required = {"agent", "role"}
    if not required.issubset({str(column).strip().casefold() for column in roles.columns}):
        raise ValueError("Agent role dataset must contain agent and role columns.")
    roles.columns = [str(column).strip().casefold() for column in roles.columns]
    roles = roles.dropna(subset=["agent", "role"]).drop_duplicates(subset=["agent"])
    return [
        {"agent": str(row.agent).strip(), "role": str(row.role).strip()}
        for row in roles.itertuples(index=False)
    ]


@lru_cache(maxsize=1)
def _get_map_names() -> tuple[str, ...]:
    from src.analytics import get_maps

    try:
        return tuple(get_maps())
    except FileNotFoundError:
        return ()


def _name_matches(text: str, names: tuple[str, ...] | list[str]) -> list[dict]:
    matches = []
    for name in names:
        aliases = [name]
        if name.casefold() == "kay/o":
            aliases.append("Kayo")
        for alias in aliases:
            pattern = re.compile(
                r"(?<![A-Za-z0-9'])" + re.escape(alias) + r"(?![A-Za-z0-9])(?!['\u2019]t\b)",
                re.IGNORECASE,
            )
            for match in pattern.finditer(text):
                if name.casefold() == "fade":
                    after = text[match.end():match.end() + 20]
                    if re.match(r"\s+(?:away|out|against|into|from|over|back)\b", after, re.IGNORECASE):
                        continue
                matches.append({"name": name, "start": match.start(), "end": match.end()})
    unique = {(item["name"], item["start"], item["end"]): item for item in matches}
    return sorted(unique.values(), key=lambda item: (item["start"], item["end"]))


def _clause_at(text: str, start: int, end: int) -> tuple[int, int]:
    left = 0
    right = len(text)
    for boundary in CLAUSE_BOUNDARY.finditer(text):
        if boundary.end() <= start:
            left = boundary.end()
        elif boundary.start() >= end:
            right = boundary.start()
            break
    return left, right


def _negation_applies(clause: str, match_index: int) -> bool:
    left_context = clause[max(0, match_index - 48):match_index]
    return bool(NEGATIONS.search(left_context))


def _phrase_score(clause: str, match_index: int, label: str, weight: float) -> tuple[float, str]:
    score = weight if label == "Positive" else -weight
    polarity = label
    if _negation_applies(clause, match_index):
        score *= -1.0
        polarity = "Negative" if label == "Positive" else "Positive"

    left_context = clause[max(0, match_index - 20):match_index]
    for intensifier, multiplier in INTENSIFIERS.items():
        if re.search(rf"\b{re.escape(intensifier)}\b", left_context, re.IGNORECASE):
            score *= multiplier
            break
    return score, polarity


def _aggregate_polarity(entries: list[dict]) -> tuple[str, float, list[str]]:
    total_score = sum(float(item["score"]) for item in entries)
    evidence = list(dict.fromkeys(item["word"] for item in entries if item.get("word")))
    if total_score > 0.5:
        return "Positive", total_score, evidence
    if total_score < -0.5:
        return "Negative", total_score, evidence
    if entries and any(item["score"] > 0 for item in entries) and any(item["score"] < 0 for item in entries):
        return "Mixed", total_score, evidence
    return "Neutral", total_score, evidence


def _polarity_for_mention(text: str, start: int, end: int) -> dict:
    left, right = _clause_at(text, start, end)
    clause = text[left:right]
    evidence = []
    scores = []

    for label, words in POLARITY_WORDS.items():
        for word, base_weight in sorted(words.items(), key=lambda item: len(item[0]), reverse=True):
            pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", re.IGNORECASE)
            for match in pattern.finditer(clause):
                score, polarity = _phrase_score(clause, match.start(), label, base_weight)
                evidence.append({
                    "word": match.group(0),
                    "label": polarity,
                    "score": score,
                    "distance": abs(left + match.start() - start),
                })
                scores.append(score)

    if not evidence:
        return {
            "sentiment": "Neutral",
            "evidence": [],
            "score": 0.0,
            "basis": "Formal clause-scoped sentiment engine: no polarity cues found near the mention.",
        }

    relevant = evidence
    nearest_distance = min(item["distance"] for item in evidence)
    nearest = [item for item in evidence if item["distance"] == nearest_distance]
    if len({item["label"] for item in nearest}) == 1:
        relevant = nearest
    sentiment, total_score, evidence_words = _aggregate_polarity(relevant)

    return {
        "sentiment": sentiment,
        "evidence": evidence_words,
        "score": round(float(total_score), 2),
        "basis": "Formal clause-scoped rule engine with weighted polarity cues, local negation handling, and contrast-aware evidence selection.",
    }


def _topic_mentions(text: str, terms: tuple[str, ...]) -> list[dict]:
    matches = []
    for term in terms:
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)
        matches.extend({"start": match.start(), "end": match.end()} for match in pattern.finditer(text))
    return sorted(matches, key=lambda item: item["start"])


def analyze_review_context(review: str) -> dict:
    text = str(review or "")
    agent_names = tuple(item["agent"] for item in get_agent_catalog())
    detected_agents = []
    for mention in _name_matches(text, agent_names):
        result = _polarity_for_mention(text, mention["start"], mention["end"])
        detected_agents.append({"agent": mention["name"], **result})

    detected_maps = []
    for mention in _name_matches(text, _get_map_names()):
        result = _polarity_for_mention(text, mention["start"], mention["end"])
        detected_maps.append({"map": mention["name"], **result})

    topics = {}
    for topic, terms in TOPIC_TERMS.items():
        mentions = _topic_mentions(text, terms)
        results = [_polarity_for_mention(text, item["start"], item["end"]) for item in mentions]
        filtered = [item for item in results if item["evidence"]]
        labels = {item["sentiment"] for item in filtered}
        evidence = list(dict.fromkeys(word for item in filtered for word in item["evidence"]))
        sentiment_score = sum(float(item.get("score", 0.0)) for item in filtered)
        if sentiment_score > 0.5:
            sentiment = "Positive"
        elif sentiment_score < -0.5:
            sentiment = "Negative"
        elif labels:
            sentiment = "Mixed" if len(labels) > 1 else next(iter(labels))
        else:
            sentiment = None
        topics[topic] = {
            "detected": bool(mentions),
            "sentiment": sentiment,
            "evidence": evidence,
            "score": round(float(sentiment_score), 2),
            "basis": "Formal topic-level score aggregation over local sentiment cues and negation windows.",
        }

    return {
        "agents": detected_agents,
        "maps": detected_maps,
        "topics": topics,
        "agent_detection_message": None if detected_agents else "No VALORANT agent detected in this review.",
        "map_detection_message": None if detected_maps else "No map detected.",
        "aspect_method": "Formal clause-scoped aspect engine with weighted polarity lexicon, negation handling, contrast-aware evidence selection, and topic aggregation.",
    }


@lru_cache(maxsize=1)
def _load_review_summary_cache() -> dict | None:
    if not SUMMARY_CACHE_PATH.exists():
        return None
    try:
        return json.loads(SUMMARY_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=1)
def _get_base_agent_sentiment_data() -> tuple[
    dict[str, dict[str, int]],
    dict[str, dict[str, dict[str, int]]],
    dict[str, float | None],
]:
    catalog = get_agent_catalog()
    counts = {item["agent"]: {label: 0 for label in SENTIMENTS} for item in catalog}
    trends: dict[str, dict[str, dict[str, int]]] = {item["agent"]: {} for item in catalog}
    avg_scores: dict[str, float | None] = {item["agent"]: None for item in catalog}

    if REVIEW_DATA_PATH == DEFAULT_REVIEW_DATA_PATH:
        cache = _load_review_summary_cache()
        if cache and isinstance(cache.get("agents"), list):
            for entry in cache["agents"]:
                agent = entry.get("agent")
                if agent not in counts:
                    continue
                counts[agent]["Positive"] = int(entry.get("positive_reviews", 0))
                counts[agent]["Neutral"] = int(entry.get("neutral_reviews", 0))
                counts[agent]["Negative"] = int(entry.get("negative_reviews", 0))
                avg_scores[agent] = entry.get("average_score")
                for point in entry.get("trend", []):
                    d = str(point.get("date", ""))
                    if d:
                        trends[agent][d] = {
                            "Positive": int(point.get("Positive", 0)),
                            "Neutral": int(point.get("Neutral", 0)),
                            "Negative": int(point.get("Negative", 0)),
                        }
            return counts, trends, avg_scores

    frame = _load_review_frame()
    for review, published_date in zip(frame["review_text"], frame["published_date"]):
        mentions = _name_matches(review, tuple(counts))
        seen = set()
        for mention in mentions:
            agent = mention["name"]
            if agent in seen:
                continue
            seen.add(agent)
            sentiment = _polarity_for_mention(review, mention["start"], mention["end"])["sentiment"]
            counts[agent][sentiment] += 1
            if pd.notna(published_date):
                date_key = published_date.date().isoformat()
                trends[agent].setdefault(date_key, {label: 0 for label in SENTIMENTS})
                trends[agent][date_key][sentiment] += 1
    return counts, trends, avg_scores


def _load_live_community_agent_reviews() -> list[dict]:
    if REVIEW_DATA_PATH != DEFAULT_REVIEW_DATA_PATH:
        return []

    collected: list[dict] = []
    try:
        from src.supabase_backend import get_supabase_agent_review_rows, is_supabase_enabled
        if is_supabase_enabled():
            collected.extend(get_supabase_agent_review_rows())
            return collected
    except Exception:
        pass

    try:
        from flask import has_app_context
        if has_app_context():
            from src.database import Review
            rows = Review.query.filter(Review.agent_name.isnot(None)).all()
            collected.extend(
                {
                    "agent_name": row.agent_name,
                    "sentiment_label": row.sentiment_label,
                    "score": float(row.rating) * 2.0,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
                if row.agent_name
            )
        else:
            from src.database import get_community_agent_review_rows
            collected.extend(get_community_agent_review_rows())
    except Exception:
        pass

    try:
        from src.database import get_live_analyzed_review_rows
        for item in get_live_analyzed_review_rows():
            for agent_name in item.get("agents", []):
                collected.append({
                    "agent_name": agent_name,
                    "sentiment_label": item.get("sentiment_label", "Neutral"),
                    "score": float(item.get("derived_score", 5.5)),
                    "created_at": item.get("created_at"),
                })
    except Exception:
        pass

    return collected


def get_sentiment_by_agent() -> list[dict]:
    catalog = get_agent_catalog()
    base_counts, base_trends, base_avg = _get_base_agent_sentiment_data()
    counts = {agent: dict(vals) for agent, vals in base_counts.items()}
    trends = {
        agent: {date_k: dict(daily) for date_k, daily in agent_trend.items()}
        for agent, agent_trend in base_trends.items()
    }
    score_sums = {}
    for agent, vals in counts.items():
        base_tot = sum(vals.values())
        score_sums[agent] = (float(base_avg[agent]) * base_tot) if (base_tot and base_avg.get(agent) is not None) else 0.0

    canonical_by_key = {
        re.sub(r"[^a-z0-9]", "", item["agent"].casefold()): item["agent"]
        for item in catalog
    }

    for row in _load_live_community_agent_reviews():
        key = re.sub(r"[^a-z0-9]", "", str(row.get("agent_name", "")).casefold())
        agent = canonical_by_key.get(key)
        if not agent:
            continue
        label = str(row.get("sentiment_label", "Neutral")).title()
        if label not in SENTIMENTS:
            label = "Neutral"
        counts[agent][label] += 1
        if row.get("score") is not None:
            score_sums[agent] += float(row["score"])
        created_raw = row.get("created_at")
        if created_raw:
            parsed = pd.to_datetime(created_raw, errors="coerce")
            if pd.notna(parsed):
                date_key = parsed.strftime("%Y-%m")
                trends[agent].setdefault(date_key, {lbl: 0 for lbl in SENTIMENTS})
                trends[agent][date_key][label] += 1

    rows = []
    for item in catalog:
        agent = item["agent"]
        total = sum(counts[agent].values())
        avg_sc = round(score_sums[agent] / total, 2) if (total and score_sums[agent] > 0) else base_avg.get(agent)
        rows.append({
            **item,
            "positive_reviews": counts[agent]["Positive"],
            "neutral_reviews": counts[agent]["Neutral"],
            "negative_reviews": counts[agent]["Negative"],
            "total_mentions": total,
            "average_score": avg_sc,
            "positive_percentage": round(counts[agent]["Positive"] / total * 100, 2) if total else 0.0,
            "neutral_percentage": round(counts[agent]["Neutral"] / total * 100, 2) if total else 0.0,
            "negative_percentage": round(counts[agent]["Negative"] / total * 100, 2) if total else 0.0,
            "trend": [
                {"date": date, **daily_counts}
                for date, daily_counts in sorted(trends[agent].items())
            ],
            "method": "Combines the 100,000+ (2020-2026) VALORANT review corpus with live community & analyzed reviews in valosent.db.",
        })
    return rows


def get_map_sentiment_summary() -> dict[str, dict]:
    """Return 100,000+ community sentiment statistics per map (for live Community Comparison cards)."""
    cache = _load_review_summary_cache() if REVIEW_DATA_PATH == DEFAULT_REVIEW_DATA_PATH else None
    raw_maps = (cache or {}).get("maps", {})
    result = {name: dict(vals) for name, vals in raw_maps.items()}

    if REVIEW_DATA_PATH == DEFAULT_REVIEW_DATA_PATH:
        try:
            from src.database import get_live_analyzed_review_rows
            for row in get_live_analyzed_review_rows():
                lbl = str(row.get("sentiment_label", "Neutral")).title()
                if lbl not in SENTIMENTS:
                    lbl = "Neutral"
                sc = float(row.get("derived_score", 5.5))
                for m_name in row.get("maps", []):
                    if m_name not in result:
                        continue
                    entry = result[m_name]
                    old_tot = int(entry.get("total_mentions", 0))
                    old_sum = float(entry.get("average_score") or 5.5) * old_tot
                    key_lbl = f"{lbl.lower()}_reviews"
                    entry[key_lbl] = int(entry.get(key_lbl, 0)) + 1
                    new_tot = old_tot + 1
                    entry["total_mentions"] = new_tot
                    entry["average_score"] = round((old_sum + sc) / new_tot, 2)
                    entry["positive_percentage"] = round(entry["positive_reviews"] / new_tot * 100, 2)
                    entry["neutral_percentage"] = round(entry["neutral_reviews"] / new_tot * 100, 2)
                    entry["negative_percentage"] = round(entry["negative_reviews"] / new_tot * 100, 2)
        except Exception:
            pass
    return result


def get_agent_review_sentiment(agent_name: str) -> dict | None:
    normalized = re.sub(r"[^a-z0-9]", "", str(agent_name).casefold())
    for item in get_sentiment_by_agent():
        key = re.sub(r"[^a-z0-9]", "", item["agent"].casefold())
        if key == normalized:
            return item
    return None