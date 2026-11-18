"""Train and compare sentiment models using one reproducible review split."""

from __future__ import annotations

import argparse
import csv
import gc
import importlib.util
import json
import logging
import random
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import LinearSVC
from src.sentiment import SENTIMENT_LABELS, create_sentiment
from src.text_processing import clean_review

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
RESULTS_DIR = BASE_DIR / "results"
QUALITY_REPORT_PATH = RESULTS_DIR / "review_data_quality.json"
ENSEMBLE_WEIGHTS_PATH = MODELS_DIR / "ensemble_weights.json"
LOGGER = logging.getLogger(__name__)

MAX_LENGTH = 200
LABELS = list(SENTIMENT_LABELS)
RANDOM_SEED = 42


def ensure_directories():
    for path in [DATA_DIR, MODELS_DIR, RESULTS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def load_dataset():
    # Clean labels and text before splitting; remove duplicate normalized reviews.
    parquet_path = DATA_DIR / "user_reviews.parquet"
    csv_path = DATA_DIR / "user_reviews.csv"

    if not parquet_path.exists() and not csv_path.exists():
        raise FileNotFoundError(
            "Dataset not found. Place user_reviews.parquet or user_reviews.csv in the data folder."
        )

    source_path = csv_path if csv_path.exists() else parquet_path
    frame = pd.read_csv(source_path) if source_path.suffix == ".csv" else pd.read_parquet(source_path)
    frame.columns = [str(column).strip().casefold() for column in frame.columns]
    missing_columns = {"review_text", "score"} - set(frame.columns)
    if missing_columns:
        raise ValueError(f"Review dataset is missing required columns: {sorted(missing_columns)}")

    source_rows = len(frame)
    missing_reviews = int(frame["review_text"].isna().sum())
    frame["review_text"] = frame["review_text"].fillna("").astype(str).str.strip()
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    invalid_scores = frame["score"].isna() | ~frame["score"].between(0, 10)
    empty_reviews = frame["review_text"].eq("")
    invalid_rows = invalid_scores | empty_reviews
    frame = frame.loc[~invalid_rows].copy()
    frame["cleaned_review"] = frame["review_text"].map(clean_review)
    empty_after_cleaning = int(frame["cleaned_review"].eq("").sum())
    frame = frame.loc[frame["cleaned_review"].ne("")].copy()
    duplicate_rows = int(frame.duplicated(["cleaned_review", "score"]).sum())
    frame = frame.drop_duplicates(["cleaned_review", "score"], keep="first")
    frame["sentiment"] = frame["score"].map(create_sentiment)
    class_counts = frame["sentiment"].value_counts().reindex(LABELS, fill_value=0)
    if frame.empty or class_counts.min() < 5:
        raise ValueError("At least five valid review examples per sentiment class are required for stratified training.")

    data_report = {
        "source_file": source_path.name,
        "source_rows": source_rows,
        "missing_review_text_rows": missing_reviews,
        "invalid_or_missing_score_rows": int(invalid_scores.sum()),
        "empty_review_rows": int(empty_reviews.sum()),
        "empty_after_cleaning_rows": empty_after_cleaning,
        "duplicate_review_score_rows_removed": duplicate_rows,
        "retained_rows": len(frame),
        "label_mapping": {"Negative": "scores 0-4", "Neutral": "scores 5-6", "Positive": "scores 7-10"},
        "class_counts": {label: int(class_counts[label]) for label in LABELS},
        "limitations": ["Sentiment labels are derived from review scores, not human annotations."],
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    QUALITY_REPORT_PATH.write_text(json.dumps(data_report, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("Loaded %s clean reviews. Label counts: %s", len(frame), data_report["class_counts"])
    return frame[["cleaned_review", "sentiment"]].to_dict(orient="records")


def train_svm(X_train, y_train, X_test, y_test, X_val=None, y_val=None):
    """Fit a calibrated linear SVM so inference exposes usable class scores."""
    # TF-IDF learns its vocabulary from training reviews; test reviews only transform.
    vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2), min_df=2)
    X_train_vec = vectorizer.fit_transform(X_train)
    # Calibration lets LinearSVC expose class scores for the cross-model ensemble.
    model = CalibratedClassifierCV(
        estimator=LinearSVC(class_weight="balanced", random_state=RANDOM_SEED),
        method="sigmoid", cv=3,
    )
    start = time.perf_counter()
    model.fit(X_train_vec, y_train)
    training_time = time.perf_counter() - start

    val_macro_f1 = None
    val_probabilities = None
    if X_val is not None and y_val is not None:
        X_val_vec = vectorizer.transform(X_val)
        val_preds = model.predict(X_val_vec)
        val_probabilities = model.predict_proba(X_val_vec)
        val_macro_f1 = float(f1_score(y_val, val_preds, average="macro", zero_division=0))

    start = time.perf_counter()
    X_test_vec = vectorizer.transform(X_test)
    predictions = model.predict(X_test_vec)
    probabilities = model.predict_proba(X_test_vec)
    inference_latency_ms = (time.perf_counter() - start) * 1000 / len(X_test)
    accuracy = accuracy_score(y_test, predictions)
    macro_f1 = f1_score(y_test, predictions, average="macro")
    weighted_f1 = f1_score(y_test, predictions, average="weighted")

    report = classification_report(
        y_test,
        predictions,
        labels=LABELS,
        target_names=LABELS,
        output_dict=True,
        zero_division=0,
    )
    matrix = confusion_matrix(y_test, predictions, labels=LABELS)

    joblib.dump(model, MODELS_DIR / "svm_model.pkl")
    joblib.dump(vectorizer, MODELS_DIR / "tfidf_vectorizer.pkl")

    return {
        "model": model,
        "vectorizer": vectorizer,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "validation_macro_f1": val_macro_f1,
        "val_probabilities": val_probabilities,
        "classification_report": report,
        "confusion_matrix": matrix,
        "training_time": training_time,
        "inference_latency_ms": inference_latency_ms,
        "test_samples": len(y_test),
        "error_examples": collect_error_examples(y_test, predictions, X_test),
        "probabilities": probabilities,
        "probability_labels": list(model.classes_),
    }


def train_naive_bayes(X_train, y_train, X_test, y_test, X_val=None, y_val=None):
    # Fit TF-IDF on training text only and weight classes to reduce majority bias.
    vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2), min_df=2)
    X_train_vec = vectorizer.fit_transform(X_train)
    X_test_vec = vectorizer.transform(X_test)
    model = MultinomialNB()
    class_counts = pd.Series(y_train).value_counts()
    sample_weights = np.asarray([
        len(y_train) / (len(LABELS) * class_counts[label]) for label in y_train
    ])
    start = time.perf_counter()
    model.fit(X_train_vec, y_train, sample_weight=sample_weights)
    training_time = time.perf_counter() - start

    val_macro_f1 = None
    val_probabilities = None
    if X_val is not None and y_val is not None:
        X_val_vec = vectorizer.transform(X_val)
        val_preds = model.predict(X_val_vec)
        val_probabilities = model.predict_proba(X_val_vec)
        val_macro_f1 = float(f1_score(y_val, val_preds, average="macro", zero_division=0))

    start = time.perf_counter()
    predictions = model.predict(X_test_vec)
    probabilities = model.predict_proba(X_test_vec)
    inference_latency_ms = (time.perf_counter() - start) * 1000 / len(X_test)
    joblib.dump(model, MODELS_DIR / "naive_bayes_model.pkl")
    joblib.dump(vectorizer, MODELS_DIR / "naive_bayes_vectorizer.pkl")
    results = classification_results(y_test, predictions, training_time, inference_latency_ms, X_test)
    results["probabilities"] = probabilities
    results["probability_labels"] = list(model.classes_)
    results["validation_macro_f1"] = val_macro_f1
    results["val_probabilities"] = val_probabilities
    return results


def train_majority_baseline(y_train, y_test, X_test):
    # This simple reference predicts the most common training label for every review.
    model = DummyClassifier(strategy="most_frequent")
    start = time.perf_counter()
    model.fit(np.zeros((len(y_train), 1)), y_train)
    training_time = time.perf_counter() - start
    start = time.perf_counter()
    predictions = model.predict(np.zeros((len(y_test), 1)))
    inference_latency_ms = (time.perf_counter() - start) * 1000 / len(X_test)
    return classification_results(y_test, predictions, training_time, inference_latency_ms, X_test)


def collect_error_examples(y_true, predictions, texts):
    return [
        {"text": str(text)[:500], "actual": str(actual), "predicted": str(predicted)}
        for text, actual, predicted in zip(texts, y_true, predictions)
        if actual != predicted
    ][:100]


def classification_results(y_true, predictions, training_time, inference_latency_ms, texts, probabilities=None):
    # Macro F1 weights each class equally; weighted F1 reflects the class proportions.
    results = {
        "accuracy": accuracy_score(y_true, predictions),
        "macro_f1": f1_score(y_true, predictions, average="macro", zero_division=0),
        "weighted_f1": f1_score(y_true, predictions, average="weighted", zero_division=0),
        "classification_report": classification_report(
            y_true, predictions, labels=LABELS, target_names=LABELS,
            output_dict=True, zero_division=0,
        ),
        "confusion_matrix": confusion_matrix(y_true, predictions, labels=LABELS),
        "training_time": training_time,
        "inference_latency_ms": inference_latency_ms,
        "test_samples": len(y_true),
        "error_examples": collect_error_examples(y_true, predictions, texts),
    }
    if probabilities is not None:
        results["probabilities"] = probabilities
    return results


def _predict_distilbert_batches(model, tokenizer, texts, batch_size=16):
    import torch

    model.eval()
    all_probs = []
    with torch.inference_mode():
        for start_idx in range(0, len(texts), batch_size):
            batch = texts[start_idx:start_idx + batch_size]
            encoded = tokenizer(batch, truncation=True, padding=True, max_length=MAX_LENGTH, return_tensors="pt")
            logits = model(**encoded).logits
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
            all_probs.append(probs)
    return np.vstack(all_probs) if all_probs else np.zeros((0, len(LABELS)))


def evaluate_saved_distilbert(X_val, y_val, X_test, y_test):
    """Evaluate an already fine-tuned DistilBERT checkpoint on the shared validation/test split."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model_dir = MODELS_DIR / "distilbert"
    if not model_dir.is_dir():
        raise FileNotFoundError(f"Saved DistilBERT checkpoint not found: {model_dir}")

    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    model_classes = [model.config.id2label[index] for index in range(len(LABELS))]
    order = [model_classes.index(label) for label in LABELS]

    val_probs = _predict_distilbert_batches(model, tokenizer, X_val)[:, order]
    val_preds = [LABELS[idx] for idx in np.argmax(val_probs, axis=1)]
    val_macro_f1 = float(f1_score(y_val, val_preds, average="macro", zero_division=0))

    start = time.perf_counter()
    test_probs = _predict_distilbert_batches(model, tokenizer, X_test)[:, order]
    inference_latency_ms = (time.perf_counter() - start) * 1000 / len(X_test)
    predicted_label_names = [LABELS[idx] for idx in np.argmax(test_probs, axis=1)]

    prior_train_time = 0.0
    eval_path = RESULTS_DIR / "model_evaluation.json"
    if eval_path.exists():
        try:
            prior = json.loads(eval_path.read_text(encoding="utf-8"))
            prior_train_time = float(
                prior.get("models", {}).get("DistilBERT", {}).get("training_time_seconds", 0.0)
            )
        except Exception:
            prior_train_time = 0.0

    results = classification_results(
        y_test, predicted_label_names, prior_train_time, inference_latency_ms, X_test, test_probs,
    )
    results["probability_labels"] = LABELS
    results["validation_macro_f1"] = val_macro_f1
    results["val_probabilities"] = val_probs
    return results


def train_distilbert(X_train, y_train, X_val, y_val, X_test, y_test):
    """Fine-tune DistilBERT; transformers/torch are required for this model."""
    try:
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            EarlyStoppingCallback,
            Trainer,
            TrainingArguments,
        )
        import torch
    except ImportError as exc:
        raise ImportError("Install transformers and torch to train DistilBERT.") from exc

    model_name = "distilbert-base-uncased"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    label_to_id = {label: index for index, label in enumerate(LABELS)}
    train_labels = [label_to_id[label] for label in y_train]
    validation_labels = [label_to_id[label] for label in y_val]
    test_labels = [label_to_id[label] for label in y_test]

    class ReviewDataset(torch.utils.data.Dataset):
        def __init__(self, texts, labels):
            self.encodings = tokenizer(texts, truncation=True, padding=True, max_length=MAX_LENGTH)
            self.labels = labels

        def __len__(self):
            return len(self.labels)

        def __getitem__(self, index):
            item = {key: torch.tensor(value[index]) for key, value in self.encodings.items()}
            item["labels"] = torch.tensor(self.labels[index])
            return item

    torch.manual_seed(RANDOM_SEED)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name, num_labels=len(LABELS), id2label=dict(enumerate(LABELS)),
        label2id=label_to_id,
    )
    output_dir = MODELS_DIR / "distilbert_checkpoints"
    training_args = {
        "output_dir": str(output_dir),
        "num_train_epochs": 5,
        "per_device_train_batch_size": 8,
        "per_device_eval_batch_size": 16,
        "save_strategy": "epoch",
        "logging_strategy": "epoch",
        "load_best_model_at_end": True,
        "metric_for_best_model": "eval_loss",
        "greater_is_better": False,
        "save_total_limit": 1,
        "report_to": "none",
        "seed": RANDOM_SEED,
        "data_seed": RANDOM_SEED,
        "fp16": False,
    }
    import inspect
    strategy_parameter = "eval_strategy" if "eval_strategy" in inspect.signature(TrainingArguments).parameters else "evaluation_strategy"
    training_args[strategy_parameter] = "epoch"
    args = TrainingArguments(**training_args)
    class_counts = np.bincount(train_labels, minlength=len(LABELS))
    class_weights = torch.tensor(
        [len(train_labels) / (len(LABELS) * count) if count else 0 for count in class_counts],
        dtype=torch.float32,
    )

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            labels = inputs.pop("labels")
            outputs = model(**inputs)
            loss = torch.nn.functional.cross_entropy(
                outputs.logits, labels, weight=class_weights.to(outputs.logits.device),
            )
            return (loss, outputs) if return_outputs else loss

    trainer = WeightedTrainer(
        model=model,
        args=args,
        train_dataset=ReviewDataset(X_train, train_labels),
        eval_dataset=ReviewDataset(X_val, validation_labels),
        callbacks=[EarlyStoppingCallback(early_stopping_patience=2)],
    )
    start = time.perf_counter()
    trainer.train()
    training_time = time.perf_counter() - start

    val_logits = trainer.predict(ReviewDataset(X_val, validation_labels)).predictions
    val_probs = tf.nn.softmax(val_logits, axis=1).numpy()
    val_preds = [LABELS[idx] for idx in np.argmax(val_probs, axis=1).tolist()]
    val_macro_f1 = float(f1_score(y_val, val_preds, average="macro", zero_division=0))

    start = time.perf_counter()
    logits = trainer.predict(ReviewDataset(X_test, test_labels)).predictions
    probabilities = tf.nn.softmax(logits, axis=1).numpy()
    predicted_ids = np.argmax(probabilities, axis=1)
    inference_latency_ms = (time.perf_counter() - start) * 1000 / len(X_test)
    model_dir = MODELS_DIR / "distilbert"
    model.save_pretrained(model_dir)
    tokenizer.save_pretrained(model_dir)
    test_label_names = [LABELS[index] for index in test_labels]
    predicted_label_names = [LABELS[index] for index in predicted_ids.tolist()]
    results = classification_results(test_label_names, predicted_label_names, training_time, inference_latency_ms, X_test, probabilities)
    results["probability_labels"] = LABELS
    results["validation_macro_f1"] = val_macro_f1
    results["val_probabilities"] = val_probs
    return results


def train_lstm(X_train, y_train, X_val, y_val, X_test, y_test, label_encoder):
    # Fit the vocabulary on training reviews only to avoid test-set leakage.
    tokenizer = tf.keras.preprocessing.text.Tokenizer(num_words=10000, oov_token="<OOV>")
    tokenizer.fit_on_texts(X_train)

    X_train_seq = tokenizer.texts_to_sequences(X_train)
    X_val_seq = tokenizer.texts_to_sequences(X_val)
    X_test_seq = tokenizer.texts_to_sequences(X_test)

    X_train_pad = tf.keras.preprocessing.sequence.pad_sequences(
        X_train_seq,
        maxlen=MAX_LENGTH,
        padding="post",
        truncating="post",
    )
    X_test_pad = tf.keras.preprocessing.sequence.pad_sequences(
        X_test_seq,
        maxlen=MAX_LENGTH,
        padding="post",
        truncating="post",
    )
    X_val_pad = tf.keras.preprocessing.sequence.pad_sequences(
        X_val_seq,
        maxlen=MAX_LENGTH,
        padding="post",
        truncating="post",
    )

    y_train_encoded = label_encoder.transform(y_train)
    y_val_encoded = label_encoder.transform(y_val)
    y_test_encoded = label_encoder.transform(y_test)
    class_counts = np.bincount(y_train_encoded, minlength=len(LABELS))
    # Dampened (square-root) inverse-frequency weights stabilize small-corpus neural training
    # without collapsing minority/majority recall.
    class_weights = {
        index: float(np.sqrt(len(y_train_encoded) / (len(LABELS) * count)))
        for index, count in enumerate(class_counts)
        if count
    }

    tf.keras.utils.set_random_seed(RANDOM_SEED)

    # Bidirectional LSTM + GlobalMaxPooling1D avoids post-padding washout on short/medium reviews.
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(MAX_LENGTH,)),
        tf.keras.layers.Embedding(input_dim=10000, output_dim=64),
        tf.keras.layers.SpatialDropout1D(0.25),
        tf.keras.layers.Bidirectional(tf.keras.layers.LSTM(48, return_sequences=True)),
        tf.keras.layers.GlobalMaxPooling1D(),
        tf.keras.layers.Dense(32, activation="relu"),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(len(LABELS), activation="softmax"),
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1.5e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )

    start = time.perf_counter()
    history = model.fit(
        X_train_pad,
        y_train_encoded,
        validation_data=(X_val_pad, y_val_encoded),
        class_weight=class_weights,
        epochs=20,
        batch_size=32,
        callbacks=[
            tf.keras.callbacks.ReduceLROnPlateau(
                monitor="val_loss", factor=0.5, patience=2, min_lr=1e-4, verbose=0,
            ),
            tf.keras.callbacks.EarlyStopping(
                monitor="val_loss", patience=4, restore_best_weights=True,
            ),
        ],
        verbose=0,
    )
    training_time = time.perf_counter() - start

    val_probabilities = model(X_val_pad, training=False).numpy()
    val_preds = label_encoder.inverse_transform(np.argmax(val_probabilities, axis=1))
    val_macro_f1 = float(f1_score(y_val, val_preds, average="macro", zero_division=0))

    start = time.perf_counter()
    test_predictions = model(X_test_pad, training=False).numpy()
    inference_latency_ms = (time.perf_counter() - start) * 1000 / len(X_test)
    predicted_indices = np.argmax(test_predictions, axis=1)
    accuracy = accuracy_score(y_test_encoded, predicted_indices)
    macro_f1 = f1_score(y_test_encoded, predicted_indices, average="macro", zero_division=0)
    weighted_f1 = f1_score(y_test_encoded, predicted_indices, average="weighted", zero_division=0)

    report = classification_report(
        y_test_encoded,
        predicted_indices,
        labels=np.arange(len(LABELS)),
        target_names=LABELS,
        output_dict=True,
        zero_division=0,
    )
    matrix = confusion_matrix(y_test_encoded, predicted_indices, labels=np.arange(len(LABELS)))

    joblib.dump(tokenizer, MODELS_DIR / "tokenizer.pkl")
    joblib.dump(label_encoder, MODELS_DIR / "label_encoder.pkl")
    model.save(MODELS_DIR / "lstm_model.keras")

    return {
        "model": model,
        "tokenizer": tokenizer,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "validation_macro_f1": val_macro_f1,
        "val_probabilities": val_probabilities,
        "classification_report": report,
        "confusion_matrix": matrix,
        "history": history,
        "training_time": training_time,
        "inference_latency_ms": inference_latency_ms,
        "test_samples": len(y_test),
        "error_examples": collect_error_examples(
            label_encoder.inverse_transform(y_test_encoded),
            label_encoder.inverse_transform(predicted_indices), X_test,
        ),
        "probabilities": test_predictions,
        "probability_labels": list(label_encoder.classes_),
    }


def save_model_comparison(model_results, methodology):
    # Save machine-readable metrics so the app can display results without retraining.
    csv_path = RESULTS_DIR / "model_comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow([
            "model",
            "accuracy",
            "macro_precision",
            "macro_recall",
            "macro_f1",
            "weighted_precision",
            "weighted_recall",
            "weighted_f1",
            "training_time_seconds",
            "inference_latency_ms_per_review",
        ])

        evaluation = {"labels": LABELS, "methodology": methodology, "models": {}}
        for model_name, results in model_results.items():
            report = results["classification_report"]
            macro = report["macro avg"]
            weighted = report["weighted avg"]
            writer.writerow([
                model_name,
                results["accuracy"],
                macro["precision"],
                macro["recall"],
                macro["f1-score"],
                weighted["precision"],
                weighted["recall"],
                weighted["f1-score"],
                results["training_time"],
                results["inference_latency_ms"],
            ])
            evaluation["models"][model_name] = {
                "accuracy": results["accuracy"],
                "training_time_seconds": results["training_time"],
                "inference_latency_ms_per_review": results["inference_latency_ms"],
                "test_samples": results["test_samples"],
                "validation_macro_f1": results.get("validation_macro_f1"),
                "classification_report": report,
                "confusion_matrix": results["confusion_matrix"].tolist(),
                "error_examples": results["error_examples"],
            }

    evaluation_path = RESULTS_DIR / "model_evaluation.json"
    with evaluation_path.open("w", encoding="utf-8") as json_file:
        json.dump(evaluation, json_file, indent=2)
        json_file.write("\n")


def compute_validation_weights(
    model_results,
    y_val=None,
    model_names=("SVM", "Naive Bayes", "LSTM", "DistilBERT"),
):
    """Optimize normalized ensemble weights on the validation split to maximize Macro F1."""
    if y_val is not None and all(model_results.get(name, {}).get("val_probabilities") is not None for name in model_names):
        aligned = []
        for name in model_names:
            entry = model_results[name]
            order = [entry["probability_labels"].index(label) for label in LABELS]
            aligned.append(np.asarray(entry["val_probabilities"])[:, order])
        stacked = np.stack(aligned, axis=0)  # (4, n_val, 3)

        # Simplex grid search (step 0.05, floor 0.05 per model so all 4 participate).
        best_score = (-1.0, -1.0)
        best_weights = [0.25, 0.25, 0.25, 0.25]
        units = 20  # 20 * 0.05 = 1.00
        for a in range(1, units - 2):
            for b in range(1, units - a - 1):
                for c in range(1, units - a - b):
                    d = units - a - b - c
                    if d < 1:
                        continue
                    w = np.asarray([a, b, c, d], dtype=float) / units
                    probs = np.tensordot(w, stacked, axes=(0, 0))
                    preds = [LABELS[idx] for idx in np.argmax(probs, axis=1)]
                    score = (
                        float(f1_score(y_val, preds, average="macro", zero_division=0)),
                        float(accuracy_score(y_val, preds)),
                    )
                    if score > best_score:
                        best_score = score
                        best_weights = w.tolist()
        return {name: round(weight, 4) for name, weight in zip(model_names, best_weights)}

    raw_scores = {}
    for name in model_names:
        val_f1 = model_results.get(name, {}).get("validation_macro_f1")
        raw_scores[name] = max(float(val_f1), 0.05) if val_f1 is not None else 1.0
    total = sum(raw_scores.values())
    return {name: round(score / total, 4) for name, score in raw_scores.items()}


def build_ensemble_results(model_results, y_test, X_test, weights=None):
    model_names = ("SVM", "Naive Bayes", "LSTM", "DistilBERT")
    probability_matrices = []
    weight_values = []
    for model_name in model_names:
        model = model_results[model_name]
        order = [model["probability_labels"].index(label) for label in LABELS]
        probability_matrices.append(np.asarray(model["probabilities"])[:, order])
        weight_values.append(float(weights[model_name]) if weights and model_name in weights else 1.0)
    weight_array = np.asarray(weight_values, dtype=float)
    weight_array = weight_array / weight_array.sum()
    probabilities = np.tensordot(weight_array, np.asarray(probability_matrices), axes=(0, 0))
    predictions = [LABELS[index] for index in np.argmax(probabilities, axis=1)]
    inference_latency_ms = sum(model_results[name]["inference_latency_ms"] for name in model_names)
    results = classification_results(
        y_test, predictions, 0.0, inference_latency_ms, X_test, probabilities,
    )
    results["probability_labels"] = LABELS
    return results


def main(reuse_distilbert: bool = False):
    ensure_directories()
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    tf.keras.utils.set_random_seed(RANDOM_SEED)
    rows = load_dataset()

    X = [row["cleaned_review"] for row in rows]
    y = [row["sentiment"] for row in rows]

    # Reserve the test partition before model selection; validation stays in development data.
    X_development, X_test, y_development, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=RANDOM_SEED,
        stratify=y,
    )
    X_train, X_validation, y_train, y_validation = train_test_split(
        X_development,
        y_development,
        test_size=0.15,
        random_state=RANDOM_SEED,
        stratify=y_development,
    )

    # The label order is fixed across models so saved probabilities remain comparable.
    label_encoder = LabelEncoder()
    label_encoder.fit(LABELS)

    results = {
        "Majority baseline": train_majority_baseline(y_train, y_test, X_test),
        "SVM": train_svm(X_train, y_train, X_test, y_test, X_val=X_validation, y_val=y_validation),
        "Naive Bayes": train_naive_bayes(X_train, y_train, X_test, y_test, X_val=X_validation, y_val=y_validation),
        "LSTM": train_lstm(
            X_train, y_train, X_validation, y_validation, X_test, y_test, label_encoder,
        ),
    }
    # Skip the large pretrained model cleanly when its optional training stack is absent.
    distilbert_ready = all(
        importlib.util.find_spec(name) for name in ("torch", "transformers", "accelerate")
    )
    ensemble_weights = None
    if distilbert_ready:
        if reuse_distilbert and (MODELS_DIR / "distilbert").is_dir():
            results["DistilBERT"] = evaluate_saved_distilbert(
                X_validation, y_validation, X_test, y_test,
            )
            distilbert_status = "trained"
        else:
            results["DistilBERT"] = train_distilbert(
                X_train, y_train, X_validation, y_validation, X_test, y_test,
            )
            distilbert_status = "trained"
        ensemble_weights = compute_validation_weights(results, y_val=y_validation)
        ENSEMBLE_WEIGHTS_PATH.write_text(
            json.dumps({"strategy": "validation_macro_f1", "weights": ensemble_weights}, indent=2) + "\n",
            encoding="utf-8",
        )
        results["Four-model ensemble"] = build_ensemble_results(
            results, y_test, X_test, weights=ensemble_weights,
        )
    else:
        distilbert_status = "skipped: install torch and transformers to train this model"
        LOGGER.warning("DistilBERT was skipped because PyTorch or Transformers is not installed.")

    # Record the split and metric definitions alongside the scores for reproducibility.
    methodology = {
        "split": "stratified 68% train / 12% validation / 20% test; preprocessing fitted on training data only",
        "random_seed": RANDOM_SEED,
        "train_samples": len(X_train),
        "validation_samples": len(X_validation),
        "test_samples": len(X_test),
        "distilbert_status": distilbert_status,
        "ensemble_strategy": "validation_macro_f1_weighted" if ensemble_weights else "equal_average",
        "ensemble_weights": ensemble_weights,
        "macro_f1": "unweighted mean of per-class F1; gives each sentiment class equal importance",
        "weighted_f1": "mean of per-class F1 weighted by class support",
        "caution": "Test-set results estimate performance for this split and score-derived labels; they are not human-annotated validation.",
    }
    save_model_comparison(results, methodology)

    print("Training complete.")
    for model_name, model_results in results.items():
        print(
            f"{model_name:20s} | acc={model_results['accuracy']:.4f} | "
            f"macro_f1={model_results['macro_f1']:.4f} | "
            f"val_macro_f1={model_results.get('validation_macro_f1')}"
        )
    if ensemble_weights:
        print(f"Ensemble weights (val macro F1): {ensemble_weights}")
    print(f"DistilBERT status: {distilbert_status}")

    gc.collect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train and evaluate VALOSENT AI sentiment models.")
    parser.add_argument(
        "--reuse-distilbert",
        action="store_true",
        help="Evaluate the existing fine-tuned DistilBERT checkpoint instead of retraining it.",
    )
    cli_args = parser.parse_args()
    main(reuse_distilbert=cli_args.reuse_distilbert)
