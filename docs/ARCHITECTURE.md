# Architecture and data flow

## System layout

```text
VALOSENT_AI/
├── app.py                     # Thin Flask HTTP routes, request validation, and CSV/JSON APIs
├── train_models.py            # Reproducible review model training, BiLSTM, DistilBERT, validation ensemble tuning
├── generate_graphs.py         # Zero-dependency SVG (and optional matplotlib PNG) figure generator
├── config/                    # Thresholds and ML hyperparameters (analytics.json, ml_model.json)
├── data/                      # Review parquet, raw/cleaned match datasets, and agent role catalog
├── docs/                      # Architecture, synopsis, final report, and presentation notes
├── models/                    # Persisted SVM, Naive Bayes, BiLSTM, DistilBERT, match LR, and ensemble_weights.json
├── research_graphs/           # Generated model accuracy and multi-metric comparison figures
├── results/                   # Persisted JSON/CSV model evaluations, confusion matrices, and data quality reports
├── src/
│   ├── __init__.py
│   ├── analytics.py           # Historical match aggregations, Wilson 95% LB rankings, and 5v5 draft context
│   ├── data_loader.py         # Match dataset cleaning, column-shift/rating sanitization, and quality report
│   ├── inference.py           # Thread-safe lazy model loader, fast inference, XAI attribution, batch & draft APIs
│   ├── ml_model.py            # Leakage-free Logistic Regression map-winner experiment
│   ├── review_analysis.py     # Clause-scoped aspect & entity polarity engine
│   ├── sentiment.py           # Score-to-label mapping and distribution summaries
│   └── text_processing.py     # Shared review text normalization
├── static/                    # VALORANT-themed CSS, Chart.js vendor bundle, and interactive dashboard JS
├── templates/                 # Unified 8-page Flask dashboard template (dashboard.html)
└── tests/                     # 26 automated unit and API integration tests
```

## Review sentiment & XAI flow

1. A browser submits a review string to `POST /api/sentiment/analyze` (or uploads a CSV / review array to `POST /api/sentiment/batch`).
2. `app.py` validates the JSON/CSV shape and 5,000-character limit before triggering lazy model loading.
3. `src/inference.py` lazily and thread-safely loads available models (`threading.Lock()`, lazy TensorFlow import, explicit `distilbert_model.eval()` and `torch.inference_mode()`).
4. Each model receives its own training-matched representation: TF-IDF for Naive Bayes and calibrated LinearSVC, saved Keras tokenizer/padding for Bidirectional LSTM (`GlobalMaxPooling1D`), and the fine-tuned tokenizer for DistilBERT.
5. `src/inference.py` combines probabilities using validation-split Macro F1 simplex weights (`models/ensemble_weights.json`), computes exact `TF-IDF × LinearSVC` per-term polarity attributions (XAI), and attaches clause-scoped aspect analysis from `src/review_analysis.py`.
6. The Model Lab reads persisted held-out metrics from `results/model_evaluation.json` rather than recomputing scores on page load.

## Review labels and measures

Scores `0–4` map to Negative, `5–6` to Neutral, and `7–10` to Positive. These labels describe score bands rather than human-annotated sentiment ground truth. The cleaned corpus retains 956 rows (469 Negative, 64 Neutral, 423 Positive) split stratified `68% / 12% / 20%` (`649` train / `115` validation / `192` test, `seed=42`).

## Match analytics & 5v5 draft flow

1. `src/data_loader.py` validates complete 5v5 map groups, removes duplicates and malformed rows, sanitizes negative/out-of-range/column-shifted metrics (`rating > 5.0` and shifted `acs-ct`), and writes `quality_report.json`.
2. `src/ml_model.py` trains a leakage-free Logistic Regression map-winner classifier using `GroupShuffleSplit` and mirrored training lineups (`models/analytics_model.pkl`).
3. `src/analytics.py` ranks map recommendations, team compositions, and agent pairings using the **Wilson 95% lower bound** after explicit minimum-support thresholds, skipping unresolved tied maps safely.
4. `POST /api/match/predict` combines `src/analytics.py` draft diagnostics (role balance warnings, historical composition stats, pair synergy) with the experimental Logistic Regression win-probability estimate.
