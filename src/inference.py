"""Thread-safe model loading, sentiment inference, XAI attribution, batch analysis, and match draft prediction."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.analytics import get_draft_context, normalize_name
from src.ml_model import make_feature_frame
from src.review_analysis import analyze_review_context
from src.sentiment import SENTIMENT_LABELS
from src.text_processing import clean_review

BASE_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = BASE_DIR / "models"
ENSEMBLE_WEIGHTS_PATH = MODELS_DIR / "ensemble_weights.json"
MATCH_MODEL_PATH = MODELS_DIR / "analytics_model.pkl"

LOGGER = logging.getLogger(__name__)
MAX_LENGTH = 200
MAX_BATCH_REVIEWS = 2000


def compute_derived_score(probabilities: np.ndarray) -> float:
    """Convert calibrated [Negative, Neutral, Positive] probabilities into a 0.0-10.0 derived score."""
    probs = np.asarray(probabilities, dtype=float)
    if probs.size != 3 or not np.isfinite(probs).all():
        return 5.5
    score = 1.6 * float(probs[0]) + 5.5 * float(probs[1]) + 9.2 * float(probs[2])
    return round(float(np.clip(score, 0.0, 10.0)), 1)

_ASSET_LOCK = threading.Lock()
_MODEL_ASSETS: dict | None = None
_MATCH_MODEL_LOCK = threading.Lock()
_MATCH_MODEL_BUNDLE: dict | None = None


def align_probabilities(probabilities, classes) -> np.ndarray:
    """Align a classifier's class probabilities into canonical SENTIMENT_LABELS order."""
    class_names = [str(label) for label in classes]
    return np.asarray(probabilities, dtype=float)[[class_names.index(label) for label in SENTIMENT_LABELS]]


def _probabilities_dict(probabilities: np.ndarray) -> dict[str, float]:
    return {
        label: round(float(probabilities[index]), 4)
        for index, label in enumerate(SENTIMENT_LABELS)
    }


def _load_ensemble_weights() -> tuple[str, dict[str, float]]:
    if ENSEMBLE_WEIGHTS_PATH.exists():
        try:
            payload = json.loads(ENSEMBLE_WEIGHTS_PATH.read_text(encoding="utf-8"))
            weights = payload.get("weights", {})
            if isinstance(weights, dict) and weights:
                return str(payload.get("strategy", "validation_macro_f1")), {
                    str(key): float(value) for key, value in weights.items()
                }
        except Exception:
            LOGGER.exception("Could not read ensemble_weights.json; falling back to equal weights.")
    return "equal_average", {}


def load_assets(force_reload: bool = False) -> dict:
    """Lazily and thread-safely load all available saved sentiment classifiers."""
    global _MODEL_ASSETS
    if _MODEL_ASSETS is not None and not force_reload:
        return _MODEL_ASSETS

    with _ASSET_LOCK:
        if _MODEL_ASSETS is not None and not force_reload:
            return _MODEL_ASSETS

        svm_path = MODELS_DIR / "svm_model.pkl"
        vectorizer_path = MODELS_DIR / "tfidf_vectorizer.pkl"
        lstm_path = MODELS_DIR / "lstm_model.keras"
        tokenizer_path = MODELS_DIR / "tokenizer.pkl"
        label_encoder_path = MODELS_DIR / "label_encoder.pkl"
        nb_model_path = MODELS_DIR / "naive_bayes_model.pkl"
        nb_vectorizer_path = MODELS_DIR / "naive_bayes_vectorizer.pkl"
        distilbert_path = MODELS_DIR / "distilbert"

        low_memory_mode = os.environ.get("VALOSENT_LOW_MEMORY", "").strip().lower() in {"1", "true", "yes"}

        assets: dict = {}
        if svm_path.exists() and vectorizer_path.exists():
            try:
                assets["svm_model"] = joblib.load(svm_path)
                assets["vectorizer"] = joblib.load(vectorizer_path)
            except Exception:
                LOGGER.exception("Could not load the saved SVM model.")

        if not low_memory_mode and all(path.exists() for path in (lstm_path, tokenizer_path, label_encoder_path)):
            try:
                import tensorflow as tf

                assets["tokenizer"] = joblib.load(tokenizer_path)
                assets["label_encoder"] = joblib.load(label_encoder_path)
                assets["lstm_model"] = tf.keras.models.load_model(lstm_path)
            except Exception:
                LOGGER.exception("Could not load the saved LSTM model.")

        if nb_model_path.exists() and nb_vectorizer_path.exists():
            try:
                assets["nb_model"] = joblib.load(nb_model_path)
                assets["nb_vectorizer"] = joblib.load(nb_vectorizer_path)
            except Exception:
                LOGGER.exception("Could not load the saved Naive Bayes model.")

        if not low_memory_mode and distilbert_path.is_dir():
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                assets["distilbert_tokenizer"] = AutoTokenizer.from_pretrained(distilbert_path)
                model = AutoModelForSequenceClassification.from_pretrained(distilbert_path)
                model.eval()
                assets["distilbert_model"] = model
            except Exception:
                LOGGER.exception("Could not load the saved DistilBERT model.")

        strategy, weights = _load_ensemble_weights()
        assets["ensemble_strategy"] = strategy
        assets["ensemble_weights"] = weights
        assets["available_models"] = [
            name for name, ready in (
                ("SVM", "svm_model" in assets),
                ("Naive Bayes", "nb_model" in assets),
                ("LSTM", "lstm_model" in assets),
                ("DistilBERT", "distilbert_model" in assets),
            )
            if ready
        ]
        _MODEL_ASSETS = assets
        return _MODEL_ASSETS


def _predict_svm(review: str, assets: dict) -> tuple[np.ndarray, dict]:
    model = assets["svm_model"]
    vector = assets["vectorizer"].transform([review])
    if hasattr(model, "predict_proba"):
        probabilities = align_probabilities(model.predict_proba(vector)[0], model.classes_)
        confidence = float(np.max(probabilities))
    else:
        label = str(model.predict(vector)[0])
        probabilities = np.eye(len(SENTIMENT_LABELS))[SENTIMENT_LABELS.index(label)]
        confidence = None

    label = SENTIMENT_LABELS[int(np.argmax(probabilities))]
    return probabilities, {
        "label": label,
        "confidence": round(confidence, 4) if confidence is not None else None,
        "derived_score": compute_derived_score(probabilities),
        "probabilities": _probabilities_dict(probabilities),
    }


def _predict_lstm(review: str, assets: dict) -> tuple[np.ndarray, dict]:
    import tensorflow as tf

    tokens = assets["tokenizer"].texts_to_sequences([review])
    padded = tf.keras.preprocessing.sequence.pad_sequences(
        tokens, maxlen=MAX_LENGTH, padding="post", truncating="post",
    )
    # Direct forward pass avoids Keras .predict() dataset overhead and memory growth on single calls.
    raw_probabilities = assets["lstm_model"](padded, training=False).numpy()[0]
    probabilities = align_probabilities(raw_probabilities, assets["label_encoder"].classes_)
    label_index = int(np.argmax(probabilities))
    return probabilities, {
        "label": SENTIMENT_LABELS[label_index],
        "confidence": round(float(probabilities[label_index]), 4),
        "derived_score": compute_derived_score(probabilities),
        "probabilities": _probabilities_dict(probabilities),
    }


def _predict_naive_bayes(review: str, assets: dict) -> tuple[np.ndarray, dict]:
    vector = assets["nb_vectorizer"].transform([review])
    probabilities = align_probabilities(
        assets["nb_model"].predict_proba(vector)[0], assets["nb_model"].classes_,
    )
    label_index = int(np.argmax(probabilities))
    return probabilities, {
        "label": SENTIMENT_LABELS[label_index],
        "confidence": round(float(probabilities[label_index]), 4),
        "derived_score": compute_derived_score(probabilities),
        "probabilities": _probabilities_dict(probabilities),
    }


def _predict_distilbert(review: str, assets: dict) -> tuple[np.ndarray, dict]:
    import torch

    encoded = assets["distilbert_tokenizer"](
        review, return_tensors="pt", truncation=True, padding=True, max_length=MAX_LENGTH,
    )
    with torch.inference_mode():
        logits = assets["distilbert_model"](**encoded).logits[0]
    raw_probabilities = torch.softmax(logits, dim=0).cpu().numpy()
    model_config = assets["distilbert_model"].config
    model_classes = [model_config.id2label[index] for index in range(len(SENTIMENT_LABELS))]
    probabilities = align_probabilities(raw_probabilities, model_classes)
    label_index = int(np.argmax(probabilities))
    return probabilities, {
        "label": SENTIMENT_LABELS[label_index],
        "confidence": round(float(probabilities[label_index]), 4),
        "derived_score": compute_derived_score(probabilities),
        "probabilities": _probabilities_dict(probabilities),
    }


def explain_review_tokens(cleaned_review: str, assets: dict, top_k: int = 6) -> dict:
    """Compute exact per-term TF-IDF x linear SVM weights driving polarity for a review."""
    model = assets.get("svm_model")
    vectorizer = assets.get("vectorizer")
    if model is None or vectorizer is None:
        return {"available": False, "method": "SVM weights unavailable", "positive_terms": [], "negative_terms": []}

    calibrated = getattr(model, "calibrated_classifiers_", None)
    if not calibrated:
        return {"available": False, "method": "Unrecognized SVM wrapper", "positive_terms": [], "negative_terms": []}

    coef_list = [
        cal.estimator.coef_
        for cal in calibrated
        if hasattr(getattr(cal, "estimator", None), "coef_")
    ]
    if not coef_list:
        return {"available": False, "method": "Linear coefficients unavailable", "positive_terms": [], "negative_terms": []}

    mean_coef = np.mean(np.stack(coef_list, axis=0), axis=0)
    classes = [str(label) for label in model.classes_]
    if "Positive" not in classes or "Negative" not in classes:
        return {"available": False, "method": "Missing polarity classes", "positive_terms": [], "negative_terms": []}

    pos_idx = classes.index("Positive")
    neg_idx = classes.index("Negative")
    vector = vectorizer.transform([cleaned_review])
    feature_names = vectorizer.get_feature_names_out()
    nonzero_indices = vector.nonzero()[1]
    if len(nonzero_indices) == 0:
        return {
            "available": True,
            "method": "TF-IDF x LinearSVC averaged fold weights (Positive minus Negative margin)",
            "positive_terms": [],
            "negative_terms": [],
        }

    contributions = []
    for idx in nonzero_indices:
        tfidf_val = float(vector[0, idx])
        net_weight = float(mean_coef[pos_idx, idx] - mean_coef[neg_idx, idx])
        impact = tfidf_val * net_weight
        contributions.append({
            "term": str(feature_names[idx]),
            "impact": round(impact, 4),
            "direction": "Positive" if impact >= 0 else "Negative",
        })

    positive_terms = sorted(
        [item for item in contributions if item["impact"] > 0.01],
        key=lambda item: item["impact"],
        reverse=True,
    )[:top_k]
    negative_terms = sorted(
        [item for item in contributions if item["impact"] < -0.01],
        key=lambda item: item["impact"],
    )[:top_k]

    return {
        "available": True,
        "method": "TF-IDF x LinearSVC averaged fold weights (Positive minus Negative margin)",
        "positive_terms": positive_terms,
        "negative_terms": negative_terms,
    }


def combine_ensemble_scores(
    scores: dict[str, np.ndarray],
    model_results: dict[str, dict],
    assets: dict,
) -> tuple[str, dict]:
    """Combine participating model probabilities using validation weights when available."""
    saved_weights = assets.get("ensemble_weights", {})
    strategy = assets.get("ensemble_strategy", "equal_average")
    active_names = list(scores.keys())

    if len(active_names) > 1 and all(name in saved_weights for name in active_names):
        raw = np.asarray([float(saved_weights[name]) for name in active_names], dtype=float)
        norm_weights = raw / raw.sum()
        used_weights = {name: round(float(w), 4) for name, w in zip(active_names, norm_weights)}
        used_strategy = strategy
    else:
        norm_weights = np.full(len(active_names), 1.0 / len(active_names), dtype=float)
        used_weights = {name: round(float(w), 4) for name, w in zip(active_names, norm_weights)}
        used_strategy = "equal_average"

    matrix = np.vstack([scores[name] for name in active_names])
    ensemble_probs = np.tensordot(norm_weights, matrix, axes=(0, 0))
    ensemble_index = int(np.argmax(ensemble_probs))
    ensemble_label = SENTIMENT_LABELS[ensemble_index]
    model_predictions = [result["label"] for result in model_results.values()]
    ensemble_name = (
        "Four-model ensemble"
        if len(scores) == 4
        else f"Ensemble ({len(scores)} available models)"
    )
    selected_model = ensemble_name if len(scores) > 1 else active_names[0]
    ensemble_result = {
        "label": ensemble_label,
        "confidence": round(float(ensemble_probs[ensemble_index]), 4),
        "score": (
            round(float(ensemble_probs[ensemble_index]), 4)
            if all(result["confidence"] is not None for result in model_results.values())
            else None
        ),
        "derived_score": compute_derived_score(ensemble_probs),
        "probabilities": _probabilities_dict(ensemble_probs),
        "agreement": sum(label == ensemble_label for label in model_predictions),
        "model_count": len(model_predictions),
        "strategy": used_strategy,
        "weights": used_weights,
    }
    return selected_model, ensemble_result


def predict_single_review(review: str, assets: dict) -> dict:
    """Run all loaded sentiment classifiers + XAI explanation on one cleaned review."""
    cleaned_review = clean_review(review)
    model_predictors = (
        ("svm_model", "SVM", "svm", _predict_svm),
        ("lstm_model", "LSTM", "lstm", _predict_lstm),
        ("nb_model", "Naive Bayes", "naive_bayes", _predict_naive_bayes),
        ("distilbert_model", "DistilBERT", "distilbert", _predict_distilbert),
    )
    scores: dict[str, np.ndarray] = {}
    model_results: dict[str, dict] = {}

    for asset_key, model_name, response_key, predict_model in model_predictors:
        if asset_key not in assets:
            continue
        try:
            probabilities, result = predict_model(cleaned_review, assets)
            scores[model_name] = probabilities
            model_results[response_key] = result
        except Exception:
            LOGGER.exception("%s prediction failed.", model_name)

    if not scores:
        raise RuntimeError("The available sentiment models could not analyze this review.")

    selected_model, ensemble_result = combine_ensemble_scores(scores, model_results, assets)
    explanation = explain_review_tokens(cleaned_review, assets)
    return {
        "cleaned_review": cleaned_review,
        **model_results,
        "ensemble": ensemble_result,
        "available_models": list(scores),
        "selected_model": selected_model,
        "overall": {"model": selected_model, **ensemble_result},
        "explanation": explanation,
    }


def analyze_reviews_batch(
    reviews: list[str],
    assets: dict,
    include_distilbert: bool = False,
) -> dict:
    """Analyze a batch of up to MAX_BATCH_REVIEWS reviews using vectorized fast models (+ optional DistilBERT)."""
    cleaned_entries = []
    skipped_empty = 0
    for index, raw_text in enumerate(reviews[:MAX_BATCH_REVIEWS]):
        raw_str = str(raw_text or "").strip()
        cleaned = clean_review(raw_str)
        if not cleaned:
            skipped_empty += 1
            continue
        cleaned_entries.append((index, raw_str, cleaned))

    if not cleaned_entries:
        raise ValueError("No valid non-empty text reviews found in the uploaded batch.")

    texts_cleaned = [item[2] for item in cleaned_entries]
    model_probs: dict[str, np.ndarray] = {}

    if "svm_model" in assets and "vectorizer" in assets:
        svm = assets["svm_model"]
        vec = assets["vectorizer"].transform(texts_cleaned)
        if hasattr(svm, "predict_proba"):
            raw = svm.predict_proba(vec)
            order = [list(map(str, svm.classes_)).index(lbl) for lbl in SENTIMENT_LABELS]
            model_probs["SVM"] = np.asarray(raw)[:, order]

    if "nb_model" in assets and "nb_vectorizer" in assets:
        nb = assets["nb_model"]
        vec = assets["nb_vectorizer"].transform(texts_cleaned)
        raw = nb.predict_proba(vec)
        order = [list(map(str, nb.classes_)).index(lbl) for lbl in SENTIMENT_LABELS]
        model_probs["Naive Bayes"] = np.asarray(raw)[:, order]

    if "lstm_model" in assets and "tokenizer" in assets and "label_encoder" in assets:
        import tensorflow as tf

        seqs = assets["tokenizer"].texts_to_sequences(texts_cleaned)
        padded = tf.keras.preprocessing.sequence.pad_sequences(
            seqs, maxlen=MAX_LENGTH, padding="post", truncating="post",
        )
        raw = assets["lstm_model"](padded, training=False).numpy()
        order = [list(map(str, assets["label_encoder"].classes_)).index(lbl) for lbl in SENTIMENT_LABELS]
        model_probs["LSTM"] = np.asarray(raw)[:, order]

    if include_distilbert and "distilbert_model" in assets and "distilbert_tokenizer" in assets:
        import torch

        tokenizer = assets["distilbert_tokenizer"]
        model = assets["distilbert_model"]
        classes = [model.config.id2label[idx] for idx in range(len(SENTIMENT_LABELS))]
        order = [classes.index(lbl) for lbl in SENTIMENT_LABELS]
        batches = []
        with torch.inference_mode():
            for start in range(0, len(texts_cleaned), 16):
                enc = tokenizer(
                    texts_cleaned[start:start + 16],
                    truncation=True,
                    padding=True,
                    max_length=MAX_LENGTH,
                    return_tensors="pt",
                )
                logits = model(**enc).logits
                batches.append(torch.softmax(logits, dim=-1).cpu().numpy()[:, order])
        model_probs["DistilBERT"] = np.vstack(batches)

    if not model_probs:
        raise RuntimeError("No sentiment models are loaded for batch analysis.")

    active_models = list(model_probs.keys())
    saved_weights = assets.get("ensemble_weights", {})
    if all(name in saved_weights for name in active_models):
        w = np.asarray([float(saved_weights[name]) for name in active_models], dtype=float)
        w = w / w.sum()
    else:
        w = np.full(len(active_models), 1.0 / len(active_models), dtype=float)

    stacked = np.stack([model_probs[name] for name in active_models], axis=0)
    ensemble_matrix = np.tensordot(w, stacked, axes=(0, 0))

    sentiment_counts = Counter()
    score_histogram = Counter()
    agent_mentions = Counter()
    agent_sent_map: dict[str, dict[str, float]] = {}
    map_mentions = Counter()
    topic_counts = Counter()
    topic_negative = Counter()
    items = []
    derived_scores_all: list[float] = []

    for row_idx, (orig_idx, raw_text, _) in enumerate(cleaned_entries):
        probs = ensemble_matrix[row_idx]
        pred_idx = int(np.argmax(probs))
        pred_label = SENTIMENT_LABELS[pred_idx]
        d_score = compute_derived_score(probs)
        derived_scores_all.append(d_score)
        score_histogram[max(0, min(10, int(round(d_score))))] += 1
        sentiment_counts[pred_label] += 1

        ctx = analyze_review_context(raw_text)
        agents_hit = [entry["agent"] for entry in ctx["agents"]]
        maps_hit = [entry["map"] for entry in ctx["maps"]]
        topics_hit = [tname for tname, tval in ctx["topics"].items() if tval["detected"]]
        for name in agents_hit:
            agent_mentions[name] += 1
            bucket = agent_sent_map.setdefault(name, {"Positive": 0, "Neutral": 0, "Negative": 0, "score_sum": 0.0})
            bucket[pred_label] += 1
            bucket["score_sum"] += d_score
        for name in maps_hit:
            map_mentions[name] += 1
        for tname in topics_hit:
            topic_counts[tname] += 1
            if ctx["topics"][tname].get("sentiment") == "Negative":
                topic_negative[tname] += 1

        items.append({
            "index": orig_idx + 1,
            "review": raw_text[:320],
            "sentiment": pred_label,
            "score": round(float(probs[pred_idx]), 4),
            "confidence": round(float(probs[pred_idx]), 4),
            "derived_score": d_score,
            "probabilities": _probabilities_dict(probs),
            "agents": agents_hit,
            "maps": maps_hit,
            "topics": topics_hit,
        })

    total = len(items)
    avg_derived = round(sum(derived_scores_all) / total, 2) if total else 0.0
    agent_breakdown = []
    for name, count in agent_mentions.most_common(12):
        b = agent_sent_map[name]
        agent_breakdown.append({
            "agent": name,
            "mentions": int(count),
            "positive": int(b["Positive"]),
            "neutral": int(b["Neutral"]),
            "negative": int(b["Negative"]),
            "avg_score": round(b["score_sum"] / count, 1) if count else 5.5,
        })

    return {
        "total_submitted": len(reviews),
        "processed_count": total,
        "skipped_empty": skipped_empty,
        "truncated": len(reviews) > MAX_BATCH_REVIEWS,
        "max_batch_size": MAX_BATCH_REVIEWS,
        "models_used": active_models,
        "average_derived_score": avg_derived,
        "score_histogram": [{"score": s, "count": int(score_histogram[s])} for s in range(11)],
        "sentiment_counts": {label: int(sentiment_counts[label]) for label in SENTIMENT_LABELS},
        "sentiment_percentages": {
            label: round(sentiment_counts[label] / total * 100, 2) for label in SENTIMENT_LABELS
        },
        "top_agents": [{"agent": name, "mentions": count} for name, count in agent_mentions.most_common(10)],
        "agent_sentiment_breakdown": agent_breakdown,
        "top_maps": [{"map": name, "mentions": count} for name, count in map_mentions.most_common(10)],
        "top_topics": [
            {"topic": name, "mentions": count, "negative_mentions": int(topic_negative[name])}
            for name, count in topic_counts.most_common()
        ],
        "items": items,
    }


def load_match_model_bundle() -> dict | None:
    """Thread-safely load the saved Logistic Regression match outcome bundle."""
    global _MATCH_MODEL_BUNDLE
    if _MATCH_MODEL_BUNDLE is not None:
        return _MATCH_MODEL_BUNDLE
    if not MATCH_MODEL_PATH.exists():
        return None
    with _MATCH_MODEL_LOCK:
        if _MATCH_MODEL_BUNDLE is not None:
            return _MATCH_MODEL_BUNDLE
        _MATCH_MODEL_BUNDLE = joblib.load(MATCH_MODEL_PATH)
        return _MATCH_MODEL_BUNDLE


def predict_match_draft(
    map_name: str,
    team1_agents: list[str],
    team2_agents: list[str],
    patch: str | None = None,
) -> dict:
    """Combine historical draft analytics with the trained Logistic Regression map-winner model."""
    context = get_draft_context(map_name, team1_agents, team2_agents)
    if context["status"] != "ok":
        return context

    bundle = load_match_model_bundle()
    ml_prediction = None
    if bundle is not None:
        canonical_map = context["map"]
        # Match model stores raw match agent spelling ("Kayo" vs "KAY/O").
        model_agent_lookup = {normalize_name(name): name for name in bundle["agents"]}
        t1_model = [model_agent_lookup.get(normalize_name(a), a) for a in context["team1"]["agents"]]
        t2_model = [model_agent_lookup.get(normalize_name(a), a) for a in context["team2"]["agents"]]
        selected_patch = str(patch).strip() if patch else (bundle["patches"][-1] if bundle.get("patches") else "6.03")

        row = pd.DataFrame([{
            "map": canonical_map,
            "patch": selected_patch,
            "team1_agents": t1_model,
            "team2_agents": t2_model,
        }])
        features = make_feature_frame(row, bundle["agents"], bundle["roles"], bundle["role_by_agent"])
        probs = bundle["pipeline"].predict_proba(features)[0]
        classes = list(bundle["pipeline"].classes_)
        team1_prob = float(probs[classes.index(1)])
        team2_prob = float(probs[classes.index(0)])
        ml_prediction = {
            "model": "Logistic Regression (Experimental)",
            "patch_used": selected_patch,
            "team1_win_probability": round(team1_prob, 4),
            "team2_win_probability": round(team2_prob, 4),
            "favored_team": "Team 1" if team1_prob >= team2_prob else "Team 2",
            "note": "Experimental pre-match lineup estimate (51.2% test accuracy); reflects historical patch/agent meta only, not player skill.",
        }

    return {
        **context,
        "ml_prediction": ml_prediction,
    }
