# VALOSENT AI

VALOSENT AI is a Flask research application for VALORANT review sentiment and historical professional-match analytics. Review labels are derived from review scores; they are not human sentiment annotations. Match recommendations use observed match data and explicit support rules, not a trained recommendation model.

## Setup

Use Python 3.11 or 3.12. From this directory, create and activate a virtual environment, then install the project dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

PyTorch and Transformers are required for DistilBERT training and inference. They are CPU-capable; a GPU is optional. If they are unavailable, training records DistilBERT as skipped and continues with the installed models. The four-model ensemble is produced only when all four sentiment classifiers can be evaluated.

## Run

Prepare the match dataset, train the match classifier, train the review classifiers, and start the web app:

```powershell
python -m src.data_loader
python -m src.ml_model
python train_models.py
python app.py
```

Open `http://127.0.0.1:5000`. The match dataset is read from `data/raw/matches/`; the cleaned file and quality report are written to `data/processed/matches/`. Put the review dataset at `data/user_reviews.parquet` or `data/user_reviews.csv`. See [data/README.md](data/README.md) for provenance and license notes.

The Flask process caches available model objects after the first request. Restart it after retraining so inference picks up new files. Model comparison results are read from `results/model_evaluation.json`; refresh the page after retraining to fetch new metrics.

## Authentication Setup (Google OAuth + Gmail 6-Digit OTP)

VALOSENT AI uses persistent SQLite (`valosent.db` via `Flask-SQLAlchemy`) for `User`, `OTPCode`, and `Review` tables and supports three login flows on `/login` and `/register`:

### 1. Google OAuth ("Continue with Google" via Authlib)
1. Copy `.env.example` to `.env`.
2. Open [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials).
3. Click **Create Credentials → OAuth client ID → Web application**.
4. Add these exact URLs:
   - **Authorized JavaScript origins:** `http://127.0.0.1:5000`
   - **Authorized redirect URIs:** `http://127.0.0.1:5000/login/google/callback`
5. Paste the generated credentials into `.env`:
   ```env
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-client-secret
   ```
6. Restart `python app.py` and click **Continue with Google** on `/login`.

### 2. Gmail 6-Digit OTP Verification (`smtplib`)
- **Live Gmail SMTP Mode:** Enable 2-Step Verification on your Google account, generate a 16-character **App Password** at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), and set these in `.env`:
  ```env
  GMAIL_USER=your-gmail@gmail.com
  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
  ```
- **Local Dev Fallback Mode (Zero Setup):** If `GMAIL_USER` / `GMAIL_APP_PASSWORD` are not filled in yet, clicking **Send OTP** still generates a hashed 6-digit OTP (5-minute TTL) in `valosent.db` and prints the code directly inside the Flask terminal console so you can test passwordless OTP login immediately.

### 3. Official VALORANT Visual Assets (`valorant-api.com`)
Official high-res agent icons, full-body portraits, role icons, and all 13 map splash wallpapers (`Summit`, `Corrode`, `Abyss`, `Sunset`, `Lotus`, `Pearl`, `Fracture`, `Breeze`, `Icebox`, `Ascent`, `Split`, `Haven`, `Bind`) are cached in `data/valorant_assets_cache.json` with guaranteed local SVG fallbacks in `static/assets/fallbacks/`. Refresh them anytime with:

```powershell
python -m src.valorant_assets
```

## Deployment

This project is ready for Render or Docker-based deployment.

- Render: the checked-in [render.yaml](render.yaml) config starts the app with Gunicorn.
- Docker: build and run with:

```bash
docker build -t valosent-ai .
docker run --rm -p 5000:5000 -e PORT=5000 valosent-ai
```

The app reads the runtime port from the `PORT` environment variable when run as a service or container.

## Project structure

- `app.py`: Flask pages, JSON/CSV APIs (`/api/sentiment/analyze`, `/api/sentiment/batch`, `/api/match/predict`, analytics endpoints), and request validation.
- `src/inference.py`: thread-safe lazy model loading, fast sentiment inference, validation-weighted ensemble, TF-IDF × LinearSVC explainability (XAI), vectorized batch analysis, and 5v5 match draft prediction.
- `train_models.py`: review quality checks, stratified 68/12/20 splits, model training (Naive Bayes, Calibrated LinearSVC, Bidirectional LSTM, DistilBERT), validation-tuned ensemble weights, and saved comparison artifacts.
- `src/text_processing.py` and `src/sentiment.py`: shared text normalization and score-to-label mapping.
- `src/data_loader.py`: professional match cleaning, outlier/column-shift sanitization, and data quality report.
- `src/ml_model.py`: map winner Logistic Regression experiment and majority baseline.
- `src/analytics.py` and `src/review_analysis.py`: match analytics, Wilson 95% lower-bound recommendations/compositions/synergies, 5v5 draft context, and clause-scoped mention-context polarity.
- `templates/` and `static/`: Flask HTML dashboard, CSS, and interactive Chart.js views (including demo presets, XAI term highlights, batch CSV upload/export, and 5v5 draft simulator).
- `results/`: measured evaluation JSON/CSV and data quality reports.

More detail is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/VIVA_AND_PRESENTATION.md](docs/VIVA_AND_PRESENTATION.md).

## Sentiment models and methodology

The review pipeline compares a majority-class baseline, Multinomial Naive Bayes, calibrated LinearSVC, Bidirectional LSTM (`GlobalMaxPooling1D`), and fine-tuned DistilBERT. TF-IDF vocabularies and neural tokenizers are fitted on training data only. Each available classifier is evaluated on the same held-out test split (192 reviews); validation data (115 reviews) is used for neural early stopping and simplex-tuned ensemble weights (`models/ensemble_weights.json`).

The score mapping is Negative (0–4), Neutral (5–6), and Positive (7–10). Macro F1 gives each class equal weight; weighted F1 weights each class by its support, so it reflects the class mix. Confusion matrices, per-class precision/recall/F1, saved errors, train time, and inference latency are stored in `results/model_evaluation.json` and `results/model_comparison.csv`.

## Current measured evaluation artifacts

On the expanded 2020–2026 review corpus (`1,246` retained reviews across all 30 agents; stratified `846` train / `150` validation / `250` test split):

- **Majority baseline:** 44.80% accuracy, 20.63% macro F1
- **Bidirectional LSTM:** 80.00% accuracy, 76.49% macro F1
- **DistilBERT:** 82.00% accuracy, 67.30% macro F1
- **Naive Bayes:** 84.40% accuracy, 80.48% macro F1
- **Calibrated LinearSVC (SVM):** 85.20% accuracy, 81.85% macro F1
- **Four-model ensemble (validation-F1 weighted):** 88.80% accuracy, 84.12% macro F1

Pass `python train_models.py --reuse-distilbert` to retrain the lightweight models and ensemble weights while reusing an existing fine-tuned `models/distilbert/` checkpoint.

The 30-agent, 13-map match-outcome experiment (`31,294` resolved maps, 2021–2026, including `Summit` and `Corrode`) reports **51.91% accuracy (51.88% macro F1)** versus **55.66% accuracy (35.47% macro F1)** for its majority baseline, and powers the live 5v5 Draft Simulator alongside historical composition and synergy data.

## Verification

Run the unit tests and syntax checks from this directory:

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py train_models.py src\analytics.py src\data_loader.py src\ml_model.py src\review_analysis.py src\sentiment.py src\text_processing.py
```

Do not redistribute the Metacritic review dataset commercially: its listed license is CC BY-NC-SA 4.0. The match data source and processing limitations are described in [data/README.md](data/README.md).
