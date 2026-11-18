# VALOSENT AI: Thesis Synopsis

## Title
VALOSENT AI: Comparative Sentiment Analysis of VALORANT Player Reviews Using Classical, Sequential, and Transformer-Based Models

## Abstract

Online gaming communities generate vast amounts of unstructured user feedback that can reveal important information about gameplay experience, balance, technical issues, and player satisfaction. In games such as VALORANT, this feedback is especially valuable because players discuss a diverse range of aspects, including agents, maps, patches, matchmaking, and performance. However, manually processing such large-scale feedback is inefficient and difficult to scale. This study presents VALOSENT AI, a web-based sentiment analysis system designed specifically for analyzing VALORANT player reviews.

The project compares four NLP approaches under a common evaluation framework: Naive Bayes, Support Vector Machines (SVM), Long Short-Term Memory (LSTM) networks, and DistilBERT. Each model is evaluated using consistent preprocessing, fair train/test splitting, and standard classification metrics such as accuracy, macro F1-score, weighted F1-score, and confusion matrices. The system further includes an aspect-aware sentiment layer that detects mentions of agents, maps, gameplay, patch notes, and matchmaking and interprets their local sentiment context.

The results demonstrate that the project successfully implements a working investigative and practical framework for VALORANT review sentiment analysis. It also highlights important limitations, especially the fact that sentiment labels are derived from review-score thresholds rather than human annotations and that the aspect-sentiment layer remains explainable and rule-based rather than fully trained. These limitations are clearly stated to maintain methodological transparency and academic integrity.

Overall, VALOSENT AI contributes a comparative and practical architecture for analyzing gaming feedback in a domain-specific setting, providing both research value and real-world usability. It offers a clear foundation for future work in larger annotated datasets, stronger aspect-level modeling, and more robust evaluation strategies.

## Problem Statement

The growth of online gaming communities has resulted in an overwhelming volume of informal player reviews and feedback. Much of this content is highly relevant to game developers and analysts, but the sheer scale and unpredictability of the language make manual analysis impractical. Traditional sentiment analysis methods often underperform on such domain-specific content because game reviews include slang, abbreviations, and gaming-specific terminology that may not be represented effectively in generic language models.

This project addresses the need for a domain-aware sentiment analysis framework for VALORANT that can compare multiple models and provide practical, explainable results.

## Objectives

1. To build a sentiment analysis system for VALORANT reviews.
2. To compare classical, sequential, and transformer-based NLP methods.
3. To evaluate the models using standard performance metrics and fairness-aware benchmarking.
4. To implement explainable aspect-level analysis for agents, maps, and game topics.
5. To package the project in a usable Flask-based web application.

## Methodology

The system uses a cleaned review dataset, normalized text, and score-based sentiment labels. Reviews are preprocessed and filtered before being used in a standard train/test workflow. The project evaluates Naive Bayes and SVM with TF-IDF vectors, an LSTM with tokenized sequences, and DistilBERT with contextual embeddings. Model performance is compared using accuracy, macro F1, weighted F1, confusion matrices, and runtime measures.

The project also includes a rule-based aspect analysis layer that detects named agents, maps, and topics and analyzes the local sentiment surrounding those mentions. This layer is designed to provide practical interpretability while acknowledging that it is not a fully trained aspect-based sentiment model.

## Key Findings

- The project establishes a working comparison framework across multiple model families.
- The system is highly relevant to esports analytics and community feedback analysis.
- Domain-specific terminology and class imbalance remain major challenges.
- Score-based labels provide a useful benchmark but are not equivalent to human annotation.
- Explainable aspect analysis adds real value even when the sentiment engine remains rule-based.

## Limitations

- Labels are score-derived rather than human-annotated.
- The neutral class is often underrepresented and harder to classify.
- Rule-based aspect analysis is transparent but not model-trained.
- Historical match analytics should be interpreted as observational summaries rather than predictions.

## Conclusion

VALOSENT AI demonstrates a practical and explainable approach to sentiment analysis for VALORANT player reviews. It brings together classical machine learning, sequential deep learning, and transformer-based methods in a coherent framework and exposes the results through an interactive web application. The project is academically and practically useful, while remaining transparent about its limits and realistic about what the data can support.
