# Viva and presentation guide

## Suggested demonstration

1. Start the app and show the dashboard's historical coverage summary.
2. Open Sentiment Analysis, submit a short review, and explain the individual predictions, model agreement, and score-derived labels.
3. Open Model Lab. Compare every available model with the majority baseline; use per-class recall and confusion matrices to discuss weak classes, not accuracy alone.
4. Open map/agent analytics and a recommendation page. Explain the support threshold and distinguish measured match rates from the rule-based ranking.
5. Finish with dataset provenance, limitations, and which models were trained in the current environment.

## Likely viva questions

**Why compare four models?**

Naive Bayes and LinearSVC are TF-IDF baselines with different decision assumptions. LSTM models token order with a recurrent neural network. DistilBERT uses contextual pretrained language representations. A shared split and metrics make the comparison fairer.

**What is TF-IDF?**

It represents terms by their frequency in one review adjusted by how common they are across training reviews. It produces sparse numeric features for Naive Bayes and SVM.

**Why use macro F1 as well as accuracy?**

Accuracy can look high when common classes dominate. Macro F1 gives Negative, Neutral, and Positive equal influence, making weak performance on Neutral more visible. Weighted F1 reflects the dataset's class proportions.

**Are the sentiment labels human annotated?**

No. They are derived from Metacritic score thresholds, so they are proxies for review sentiment and can disagree with the wording of a review.

**How is data leakage reduced?**

The review corpus is split into train, validation, and test partitions before fitting vectorizers or tokenizers. Validation is used for neural early stopping; the held-out test partition is reserved for final comparison. Match post-outcome statistics are excluded from the map-winner model.

**Does the ensemble guarantee higher accuracy?**

No. Its measured held-out metrics must be compared with every individual model and the majority baseline. Its average model score is not a calibrated probability.

**What does the map recommendation mean?**

It summarizes historical observations with minimum sample support. An overall map win-rate ranking uses a Wilson lower bound; attack/defense views use player ACS summaries because the source does not provide reliable side-win labels.

**What are the main limitations?**

The review corpus is small and imbalanced, labels are score-derived, and the neutral class has low support. Match data is historical and lacks event, region, explicit match identifiers, and starting-side information. Mention-based aspect sentiment is a formal rule-based layer with weighted local polarity cues, clause scoping, and negation handling; it is not a trained aspect model.

## Reproducibility notes

Use Python 3.11 or 3.12, install `requirements.txt`, record the generated review quality report and model evaluation JSON/CSV, and note the seed and split sizes. DistilBERT requires PyTorch, Transformers, a pretrained checkpoint download, and additional CPU time; the GPU is optional. Do not quote old checked-in metrics as results from a new training run.
