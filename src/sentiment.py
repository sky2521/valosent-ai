from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_DATA_PATH = BASE_DIR / "data" / "user_reviews.parquet"
REVIEW_DATA_PATH = DEFAULT_REVIEW_DATA_PATH
SUMMARY_CACHE_PATH = BASE_DIR / "data" / "review_summary_cache.json"
SENTIMENT_LABELS = ("Negative", "Neutral", "Positive")
SCORE_MIN = 0
SCORE_MAX = 10


@lru_cache(maxsize=1)
def _load_summary_cache() -> dict | None:
    if not SUMMARY_CACHE_PATH.exists():
        return None
    try:
        return json.loads(SUMMARY_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _should_use_cache() -> bool:
    return REVIEW_DATA_PATH == DEFAULT_REVIEW_DATA_PATH and SUMMARY_CACHE_PATH.exists()


@lru_cache(maxsize=1)
def _get_valid_scores() -> pd.Series:
    if not REVIEW_DATA_PATH.exists():
        raise FileNotFoundError(f"Review dataset not found: {REVIEW_DATA_PATH}")

    frame = pd.read_parquet(REVIEW_DATA_PATH)
    score_column = next(
        (column for column in frame.columns if str(column).strip().casefold() == "score"),
        None,
    )
    if score_column is None:
        raise ValueError("Review dataset must contain a score column.")

    scores = pd.to_numeric(frame[score_column], errors="coerce").dropna()
    return scores[scores.between(SCORE_MIN, SCORE_MAX)]


def create_sentiment(score: float | str) -> str:
    numeric_score = float(score)
    if not SCORE_MIN <= numeric_score <= SCORE_MAX:
        raise ValueError(f"Score must be between {SCORE_MIN} and {SCORE_MAX}.")
    if numeric_score <= 4:
        return "Negative"
    if numeric_score <= 6:
        return "Neutral"
    return "Positive"


def _load_live_analyzed_rows() -> list[dict]:
    if not _should_use_cache():
        return []
    try:
        from src.database import get_live_analyzed_review_rows
        return get_live_analyzed_review_rows()
    except Exception:
        return []


def get_sentiment_distribution() -> dict:
    if _should_use_cache():
        cache = _load_summary_cache()
        if cache:
            counts = {lbl: int(cache["sentiment_counts"].get(lbl, 0)) for lbl in SENTIMENT_LABELS}
            live_rows = _load_live_analyzed_rows()
            for row in live_rows:
                lbl = str(row.get("sentiment_label", "")).title()
                if lbl in counts:
                    counts[lbl] += 1
            total = sum(counts.values())
            return {
                "total_reviews": int(total),
                "live_analyzed_count": len(live_rows),
                "average_score": float(cache.get("average_score", 6.1)),
                "date_range": cache.get("date_range", "2020-06-02 to 2026-11-15"),
                "label_source": cache.get(
                    "label_source",
                    "VALORANT 2020-2026 player review corpus (100,000+ reviews; score thresholds 0-4 Negative, 5-6 Neutral, 7-10 Positive)",
                ),
                "labels": list(SENTIMENT_LABELS),
                "counts": counts,
                "percentages": {
                    label: (round(counts[label] / total * 100, 2) if total else 0.0)
                    for label in SENTIMENT_LABELS
                },
                "topic_sentiment": None,
                "patch_sentiment": None,
            }

    scores = _get_valid_scores()
    labels = scores.map(create_sentiment)
    counts = labels.value_counts().reindex(SENTIMENT_LABELS, fill_value=0)
    total = int(counts.sum())

    return {
        "total_reviews": total,
        "live_analyzed_count": 0,
        "average_score": round(float(scores.mean()), 2) if total else None,
        "label_source": "VALORANT Metacritic score thresholds; not human sentiment annotation",
        "labels": list(SENTIMENT_LABELS),
        "counts": {label: int(counts[label]) for label in SENTIMENT_LABELS},
        "percentages": {
            label: (round(float(counts[label]) / total * 100, 2) if total else 0.0)
            for label in SENTIMENT_LABELS
        },
        "topic_sentiment": None,
        "patch_sentiment": None,
    }


def get_score_distribution() -> dict:
    if _should_use_cache():
        cache = _load_summary_cache()
        if cache:
            score_counts = {s: int(cache["score_counts"].get(str(s), 0)) for s in range(SCORE_MIN, SCORE_MAX + 1)}
            live_rows = _load_live_analyzed_rows()
            for row in live_rows:
                bucket = max(SCORE_MIN, min(SCORE_MAX, int(row.get("score_bucket", 5))))
                score_counts[bucket] += 1

            total = sum(score_counts.values())
            by_sentiment = {}
            for lbl, rng_scores in (("Negative", range(0, 5)), ("Neutral", range(5, 7)), ("Positive", range(7, 11))):
                cnt = sum(score_counts[s] for s in rng_scores)
                s_sum = sum(s * score_counts[s] for s in rng_scores)
                by_sentiment[lbl] = {
                    "count": int(cnt),
                    "percentage": round(cnt / total * 100, 2) if total else 0.0,
                    "average_score": round(s_sum / cnt, 2) if cnt else None,
                }
            overall_avg = round(sum(s * cnt for s, cnt in score_counts.items()) / total, 2) if total else None
            return {
                "total_reviews": int(total),
                "live_analyzed_count": len(live_rows),
                "average_score": overall_avg,
                "score_column": "score",
                "score_distribution": [
                    {"score": float(s), "count": int(score_counts[s])}
                    for s in range(SCORE_MIN, SCORE_MAX + 1)
                ],
                "sentiment_distribution": by_sentiment,
                "label_mapping": {
                    "negative": f"{SCORE_MIN}-4",
                    "neutral": "5-6",
                    "positive": f"7-{SCORE_MAX}",
                },
            }

    scores = _get_valid_scores()
    score_counts = scores.value_counts().sort_index()
    labels = scores.map(create_sentiment)
    total = int(len(scores))

    by_sentiment = {}
    for label in SENTIMENT_LABELS:
        label_scores = scores[labels.eq(label)]
        count = int(len(label_scores))
        by_sentiment[label] = {
            "count": count,
            "percentage": round(count / total * 100, 2) if total else 0.0,
            "average_score": round(float(label_scores.mean()), 2) if count else None,
        }

    return {
        "total_reviews": total,
        "live_analyzed_count": 0,
        "average_score": round(float(scores.mean()), 2) if total else None,
        "score_column": "score",
        "score_distribution": [
            {"score": float(score), "count": int(score_counts[score])}
            for score in score_counts.index
        ],
        "sentiment_distribution": by_sentiment,
        "label_mapping": {
            "negative": f"{SCORE_MIN}-4",
            "neutral": "5-6",
            "positive": f"7-{SCORE_MAX}",
        },
    }
