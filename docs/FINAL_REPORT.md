# VALOSENT AI: Comparative Sentiment Analysis of VALORANT Player Reviews Using Classical, Sequential, and Transformer-Based Models

## Abstract

The rapid growth of online gaming communities has created an unprecedented volume of player feedback, including reviews, comments, complaints, and suggestions related to gameplay mechanics, agents, maps, patches, matchmaking, and technical performance. In a live-service game such as VALORANT, this feedback contains valuable information that can inform balancing decisions, content updates, and player experience improvements. However, the volume and informal nature of such reviews make manual analysis inefficient and impractical at large scale. This project introduces VALOSENT AI, a web-based sentiment analysis platform designed to process player reviews for VALORANT and classify their sentiment using multiple machine learning and deep learning approaches.

The system comparatively evaluates Naive Bayes, Support Vector Machines (SVM), Long Short-Term Memory (LSTM) networks, and DistilBERT on a shared review dataset. Each model is trained and tested under a consistent pipeline to ensure fair comparison using common evaluation metrics, including accuracy, macro F1-score, weighted F1-score, and confusion matrices. In addition to sentiment classification, the platform also performs aspect-aware analysis to detect mentions of agents, maps, and gameplay-related topics and infer their local polarity from contextual cues.

The project emphasizes explainability and practical utility by packaging the analysis in a Flask-based web application that presents results through a dashboard. It also makes a clear distinction between model-based sentiment prediction and rule-based aspect analysis, which is important because the review labels are derived from score thresholds rather than human annotation. The proposed system demonstrates the feasibility of deploying a domain-aware sentiment intelligence framework for esports feedback analysis while also highlighting important limitations related to class imbalance, score-based labels, and heuristic aspect detection.

## 1. Introduction

Online games and social media platforms generate a large stream of user-generated feedback that reflects player experiences, frustrations, and preferences. In multiplayer games such as VALORANT, players often discuss a wide range of issues, including agent balance, gunplay, matchmaking quality, map design, technical performance, and game patches. These conversations contain information that is highly relevant to game developers, community managers, analysts, and researchers. However, manually processing this feedback at scale is expensive, time-consuming, and difficult to reproduce consistently.

Sentiment analysis provides a way to automatically interpret large amounts of text and convert it into structured information. Traditional sentiment analysis methods have been used in many domains, including product reviews, social media, customer feedback, and online communities. However, video game reviews often include domain-specific vocabulary and informal expressions that are not always captured well by generic sentiment models. Terms such as “nerfed”, “buffed”, “broken”, “cooked”, and “clutch” may carry meaning that differs sharply from casual conversational usage. This makes it important to design systems that are both domain-aware and transparent in their decision-making.

VALOSENT AI addresses this challenge by providing a specialized framework for analyzing VALORANT player reviews. The project compares multiple text-classification methods: a classical probabilistic model (Naive Bayes), a margin-based classifier (SVM), a sequential deep-learning model (LSTM), and a transformer-based model (DistilBERT). The project is not limited to general sentiment classification; it also supports aspect-level analysis by detecting references to specific agents and topics in reviews and calculating their sentiment using local textual context. The final system is implemented as a Flask application, allowing users to submit reviews and view sentiment outputs through a web-based interface.

The motivation for this research is therefore twofold. First, it addresses a real need in esports analytics: converting unstructured player feedback into meaningful sentiment and topic insights. Second, it contributes a comparative evaluation of multiple NLP methods within a single domain-specific framework, making it easier to understand the strengths and trade-offs associated with each approach.

## 2. Problem Statement

Although sentiment analysis has been widely studied in general text mining and review analysis, there remains a gap in research focusing on game-specific feedback, particularly in competitive online games like VALORANT. Traditional sentiment models often struggle with domain-specific expressions, player slang, and implicit sentiment encoded in short, noisy, and highly contextual reviews.

Moreover, a practical system should do more than classify a review as positive, neutral, or negative. It should also identify which aspects of the game the review is discussing: agents, maps, matchmaking, patches, performance, or gameplay. This kind of fine-grained analysis is essential for understanding not just whether players are satisfied, but what they are satisfied or dissatisfied with.

The specific challenge addressed by this project is the design and implementation of a sentiment analysis system for VALORANT reviews that is able to:

- process large-scale review text in a domain-specific format;
- compare multiple model families under a common evaluation protocol;
- handle the class imbalance that often appears in review datasets;
- identify relevant game entities and topics in text;
- present results through an interpretable and user-friendly interface.

The project also recognizes that review labels in many gaming datasets are often derived from numeric score bands rather than manually assigned human sentiment labels. This limitation must be reported transparently, since it affects how the model should be interpreted and how strongly any sentiment result can be claimed to represent true human opinion.

## 3. Objectives of the Study

The objectives of the project are as follows:

1. To build a VALORANT-focused sentiment analysis system for review text.
2. To compare classical, sequential, and transformer-based NLP models in the same review evaluation setting.
3. To apply consistent preprocessing, feature extraction, and train/test procedures across all models.
4. To evaluate model performance using class-aware metrics such as accuracy, macro F1-score, weighted F1-score, and confusion matrices.
5. To detect aspect-related mentions such as agents, maps, patch notes, and gameplay performance and estimate their sentiment.
6. To present the results through a real web application that supports practical experimentation and demonstration.

## 4. Literature Review

Sentiment analysis has emerged as one of the most active areas in natural language processing. Early work in text classification established that sentiment tasks can be treated as supervised classification problems, with machine learning models learning patterns from labeled text data. These approaches became especially useful for product reviews, social media analysis, and opinion mining, where the presence of domain-specific language and informal phrasing made rule-based interpretation difficult.

Pang and Lee established sentiment classification as a machine-learning task based on text categorization, demonstrating the usefulness of supervised methods for opinion detection. Joachims and others showed that Support Vector Machines are highly effective for high-dimensional text data, which is particularly relevant to sparse representations such as TF-IDF. These classical models remain strong baselines for many sentiment tasks because they are computationally efficient and interpretable.

Sequential models such as Long Short-Term Memory (LSTM) networks were introduced to capture temporal information and word dependencies in text. Unlike bag-of-words models, LSTMs consider order and context, allowing them to model the structure of a sentence more effectively. In review classification, these models can capture subtle relationships between words that may influence sentiment.

Transformer-based models marked a major breakthrough in natural language processing. BERT and its distilled variant, DistilBERT, use contextual embeddings and pretraining on large text corpora, allowing them to model semantics more effectively than traditional frequency-based approaches. DistilBERT is particularly attractive because it preserves much of the contextual power of BERT while being lighter and more computationally manageable.

The application of these methods to gaming-related feedback is highly relevant due to the domain-specific vocabulary and highly contextual language used by players. Terms like “nerfed”, “buffed”, “broken”, “cooked”, and “meta” are not generally neutral or obvious in sentiment, and they often depend on surrounding context. This motivates the design of a VALORANT-specific sentiment pipeline that compares multiple model families under the same conditions and integrates a rule-based aspect analysis layer to provide domain-aware explanations.

## 5. Methodology

### 5.1 Data Collection and Label Construction

The project uses a VALORANT review dataset containing review text and associated score values. Since the system is designed for practical analysis and the data does not contain fully human-annotated sentiment labels, sentiment classes are derived from the score thresholds. In this project, the mapping is defined as follows:

- 0–4 = Negative
- 5–6 = Neutral
- 7–10 = Positive

This labeling strategy is consistent with the review-scale semantics and allows the dataset to be turned into a three-class sentiment classification problem. However, it is important to emphasize that these labels represent score bands rather than human-annotated sentiment truth. They are therefore useful for benchmarking and model training, but they should not be presented as a ground-truth sentiment interpretation in the same way as manually labeled annotations.

### 5.2 Data Cleaning and Preprocessing

Before model training, the review data undergoes cleaning and validation. This includes:

- removal of empty or malformed review entries;
- filtering out invalid numeric scores;
- normalization of whitespace and text formatting;
- deduplication of repeated normalized review-score pairs;
- transformation of reviews into a consistent representation for downstream models.

The preprocessing stage is essential because gaming reviews often contain noise, repeated text, and short informal phrases. The same cleaned dataset is used across all model families to maintain fairness in the comparison.

### 5.3 Model Pipeline

The system implements four classification approaches:

1. Multinomial Naive Bayes with TF-IDF features
2. Linear SVM with TF-IDF features
3. LSTM with tokenization and embedding-based sequence modeling
4. DistilBERT with contextual embeddings and a classification head

Each model is evaluated on the same held-out test partition, and preprocessing is learned only from training data to reduce data leakage. The project also uses validation data in the deep-learning workflow for early stopping and tuning, while reserving the final test set for reporting model performance.

### 5.4 Evaluation Metrics

To evaluate performance fairly, the system reports multiple metrics:

- Accuracy: proportion of correctly classified reviews
- Macro F1-score: average F1-score across all classes equally
- Weighted F1-score: class-weighted F1-score reflecting the class distribution
- Confusion matrices: to identify per-class misclassification patterns
- Training time and inference latency: to compare model efficiency

These metrics are especially useful in imbalanced datasets, where accuracy alone can be misleading. In the current project, the neutral class is typically the weakest category because it has much lower support than positive and negative labels.

### 5.5 Aspect-Based Review Analysis

In addition to general sentiment classification, the project includes an aspect-analysis component that looks for mentions of game-related entities and topics. The system detects:

- agent names,
- map names,
- gameplay topics,
- matchmaking discussions,
- patch/update discussions,
- performance-related issues such as FPS and ping.

The system then applies a local contextual polarity engine to infer the sentiment associated with each detected aspect. This engine uses weighted sentiment words, clause boundaries, and negation handling to determine the polarity around a mention. While this is not a trained aspect-model, it is a valuable explainable layer for understanding how a review is framed around game entities and issues.

## 6. System Architecture

The project is structured as a layered system that separates the major responsibilities of the application:

### 6.1 Data Layer
The data layer contains the review corpus, cleaned match analytics data, and the configuration files required for preprocessing and evaluation. The project uses processed review data and historical match records for analysis and dashboard generation.

### 6.2 Model Layer
This layer contains the model training logic, raw feature extraction, model serialization, and evaluation metrics. It is responsible for fitting the TF-IDF models, training the LSTM, and loading the DistilBERT checkpoint when available.

### 6.3 Aspect Analysis Layer
The aspect-analysis layer detects entities and topics in a review and applies local contextual sentiment scoring. This layer is designed to explain which game elements are being discussed and whether they are described positively or negatively.

### 6.4 Application Layer
The Flask application exposes the model and analysis functionality through REST APIs and a browser-based interface. It allows users to:

- submit a review,
- view individual model outputs,
- inspect ensemble predictions,
- analyze aspect-level sentiment,
- browse agent and map statistics,
- access the dashboard and summary views.

This architecture makes the project useful as both a research prototype and a practical demonstration platform.

## 7. Results and Discussion

The project demonstrates that a domain-specific sentiment system for VALORANT review data can be built and evaluated in a unified pipeline. The strongest contribution is not simply that the system classifies reviews, but that it provides a comparative view of different model families in the same environment.

The classical models provide strong baselines and are efficient to train. Naive Bayes is computationally lightweight, while SVM is known for its effectiveness on high-dimensional sparse text features. LSTM offers a sequential modeling perspective that can capture word order and sentence structure, while DistilBERT brings contextualized language understanding that is particularly useful in noisy and informal review texts.

The project also reveals an important lesson in real-world review analytics: model performance is highly dependent on the quality and structure of the dataset. The review labels are score-derived rather than human-annotated, which can introduce mismatches between the numeric score and the actual sentiment implied by wording. This is especially relevant for borderline reviews or neutral statements, which often contain both positive and negative signals.

The aspect-based analysis is also a significant addition because it moves beyond a single sentiment label and provides some interpretability. Users can see which agents, maps, or topics were mentioned in a review and what sentiment is associated with those mentions. This is valuable for game analysis because player feedback is rarely monolithic: a player may praise a weapon or agent while criticizing matchmaking or a recent patch.

Nevertheless, it is important to be honest about the project’s limitations. The review dataset is not large enough to guarantee robust performance across all sentiment classes, especially Neutral. The aspect analysis layer is rule-based and explainable, but it is not a trained aspect-sentiment model. Therefore, it should be interpreted as a transparent heuristic layer rather than a definitive labeler of topical sentiment.

## 8. Limitations

This project has several limitations that must be acknowledged:

1. Score-derived labels: Sentiment labels are derived from review score bands rather than human annotation, so they may not perfectly reflect linguistic sentiment.
2. Class imbalance: The neutral class is typically underrepresented, which can reduce model recall and make macro F1 a more important metric than raw accuracy.
3. Heuristic aspect analysis: The mention-based sentiment system is explainable and useful, but not trained on manually labeled aspect data.
4. Dataset constraints: The project does not claim perfect real-world generalization beyond the review corpus used for training.
5. Historical match data: Match analytics and recommendations are based on historical observations and should not be treated as guaranteed prediction signals.

These limitations do not invalidate the project. Instead, they define realistic boundaries for the methodology and ensure that conclusions remain evidence-based and transparent.

## 9. Conclusion

VALOSENT AI demonstrates the feasibility of building a domain-specific sentiment analysis platform for VALORANT player reviews. The system combines classical, sequential, and transformer-based NLP approaches into a unified framework and evaluates them under a consistent computational setup. It offers a practical route for converting unstructured player feedback into machine-readable sentiment and topic insights while also supporting interpretable outputs through a web application.

The project is valuable not only as a technical implementation, but also as a case study in how gaming feedback can be analyzed at scale. It shows that sentiment classification in esports feedback is feasible and useful, while also highlighting the importance of honest model evaluation, transparent reporting, and domain-aware interpretation of results.

The core academic contribution of this project lies in its comparative viewpoint: it does not rely on a single model, but evaluates multiple approaches under the same conditions and explains the trade-offs between them. This makes the system useful for both research and practical decision-making.

Future work can improve the system by collecting larger and more carefully human-annotated datasets, strengthening the aspect-sentiment model, and improving calibration and evaluation methodology. Such improvements would move the project from a strong prototype toward a more rigorous research-grade sentiment intelligence system for esports communities and game developers.

## 10. Future Work

Future research directions for VALOSENT AI include:

- acquiring manually annotated VALORANT review datasets for higher-quality ground truth;
- expanding aspect-based sentiment modeling with trained classifiers rather than rule-based heuristics;
- improving class balance for neutral sentiment and domain-specific vocabulary;
- calibrating model probabilities to support clearer confidence interpretation;
- integrating larger topic taxonomies for agents, maps, performance, economy, and patches;
- extending the dashboard with live analytics and exportable reports.

These extensions would improve robustness, generalization, and the overall research value of the system.

## References

The literature foundation of this project is drawn from established work in sentiment classification, support vector machines, LSTM networks, transformer-based language models, and domain-specific application of NLP to online reviews. The project also incorporates domain-relevant considerations specific to VALORANT and online gaming terminology.

## Appendix A: Summary of Key Project Contributions

- Unified comparative evaluation of Naive Bayes, SVM, LSTM, and DistilBERT
- Domain-specific V ALORANT review analysis pipeline
- Explainable aspect detection for agents, maps, gameplay, and patches
- Web-based interface for practical use and demonstration
- Honest limitation reporting about score-derived labels and rule-based analysis

## Appendix B: Ethical and Practical Considerations

This project should be understood as a practical decision-support tool, not as a definitive source of human emotional truth. The requirement to assess model performance honestly is especially important in gaming and review analytics, where labels may be derived from numerical scores and where informal or sarcastic language can distort sentiment interpretation. For that reason, the project emphasizes transparency, explainability, and methodological clarity rather than claiming perfect predictive authority.
