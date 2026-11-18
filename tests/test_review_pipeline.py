import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import train_models
from src.sentiment import SENTIMENT_LABELS
from src.text_processing import clean_review


class TextProcessingTests(unittest.TestCase):
    def test_training_and_inference_share_normalization(self):
        self.assertEqual(clean_review("Jett &amp; Sage are GREAT! https://example.com"), "jett sage are great")
        self.assertEqual(clean_review(None), "")


class ReviewDatasetTests(unittest.TestCase):
    def test_invalid_rows_and_duplicate_review_labels_are_removed(self):
        rows = []
        words = ("alpha", "bravo", "charlie", "delta", "echo")
        for score, label in ((2, "negative"), (5, "neutral"), (9, "positive")):
            for word in words:
                rows.append({"review_text": f"{label} distinct review {word}", "score": score})
        rows.extend([
            {"review_text": "negative distinct review alpha", "score": 2},
            {"review_text": "missing score", "score": "bad"},
            {"review_text": "   ", "score": 4},
        ])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pd.DataFrame(rows).to_csv(root / "user_reviews.csv", index=False)
            with patch.object(train_models, "DATA_DIR", root), patch.object(
                train_models, "RESULTS_DIR", root / "results"
            ), patch.object(train_models, "QUALITY_REPORT_PATH", root / "results" / "quality.json"):
                dataset = train_models.load_dataset()
                report = json.loads((root / "results" / "quality.json").read_text(encoding="utf-8"))

        self.assertEqual(len(dataset), 15)
        self.assertEqual(report["duplicate_review_score_rows_removed"], 1)
        self.assertEqual(report["invalid_or_missing_score_rows"], 1)
        self.assertEqual(report["empty_review_rows"], 1)
        self.assertEqual(report["class_counts"], {"Negative": 5, "Neutral": 5, "Positive": 5})


class EvaluationTests(unittest.TestCase):
    def test_tfidf_models_fit_on_training_data_and_produce_test_metrics(self):
        labels = ["Negative", "Neutral", "Positive"]
        train_texts = [f"{label.lower()} gameplay review example {word}" for label in labels for word in (
            "alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
        )]
        train_labels = [label for label in labels for _ in range(6)]
        test_texts = ["negative gameplay review sample", "neutral gameplay review sample", "positive gameplay review sample"]
        test_labels = labels
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            train_models, "MODELS_DIR", Path(temp_dir)
        ):
            svm = train_models.train_svm(train_texts, train_labels, test_texts, test_labels)
            naive_bayes = train_models.train_naive_bayes(train_texts, train_labels, test_texts, test_labels)

        self.assertEqual(svm["probabilities"].shape, (3, 3))
        self.assertEqual(naive_bayes["probabilities"].shape, (3, 3))
        self.assertEqual(svm["test_samples"], 3)
        self.assertEqual(naive_bayes["test_samples"], 3)

    def test_classification_results_keep_per_class_metrics_and_errors(self):
        results = train_models.classification_results(
            ["Negative", "Neutral", "Positive"],
            ["Negative", "Positive", "Positive"],
            1.0,
            2.0,
            ["bad", "mixed", "good"],
        )
        self.assertEqual(results["classification_report"]["Neutral"]["recall"], 0.0)
        self.assertEqual(results["error_examples"][0]["actual"], "Neutral")
        self.assertEqual(results["error_examples"][0]["predicted"], "Positive")

    def test_four_model_ensemble_averages_in_label_order(self):
        probabilities = np.asarray([
            [0.8, 0.1, 0.1],
            [0.1, 0.2, 0.7],
        ])
        model_results = {
            name: {
                "probability_labels": list(SENTIMENT_LABELS),
                "probabilities": probabilities,
                "inference_latency_ms": 1.0,
            }
            for name in ("SVM", "Naive Bayes", "LSTM", "DistilBERT")
        }
        results = train_models.build_ensemble_results(
            model_results,
            ["Negative", "Positive"],
            ["bad", "good"],
        )
        self.assertEqual(results["accuracy"], 1.0)
        self.assertEqual(results["test_samples"], 2)
        self.assertEqual(results["inference_latency_ms"], 4.0)


if __name__ == "__main__":
    unittest.main()
