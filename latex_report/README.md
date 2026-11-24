# Valosent AI: MCA Major Project Report (Overleaf LaTeX Package)

**Author:** SK Imam (Roll No: 2501940067)  
**Program:** Master of Computer Applications (AI & ML), Semester-III  
**Institution:** Department of Computer Science and Engineering, School of Engineering and Technology, K.R. Mangalam University, Gurugram  
**Date:** November 2026  

---

## 🚀 1-Click Overleaf Setup Guide

1. **Login to Overleaf:** Go to [https://www.overleaf.com](https://www.overleaf.com) and log in.
2. **Create New Project:** Click **New Project** $\to$ **Upload Project**.
3. **Upload the ZIP:** Drag and drop `Valosent_AI_LaTeX_Report_Overleaf.zip`.
4. **Compile:** 
   - Overleaf will automatically detect `main.tex` as the root document.
   - Click **Recompile** (Compiler: **pdfLaTeX** or **XeLaTeX**; TeX Live version: 2022, 2023, or 2024).
   - Your publication-grade 50–54 page report PDF will generate cleanly with **zero missing image warnings**.

---

## 📁 Repository & File Architecture

```
latex_report/
│
├── main.tex                 # Master driver file (preamble, Roman frontmatter, Arabic chapters, annexures)
├── preamble.tex             # Document geometry, Times font, listings, TikZ libraries, pgfplots, fancyhdr
├── frontmatter.tex          # KRMU Title Page (vector crest), Declaration, Certificate, Abstract, TOC/LOF/LOT
├── references.tex           # 20 complete IEEE academic citations (Overleaf-ready \thebibliography)
├── annexures.tex            # Plagiarism Declaration (<15% similarity), Full Python source code listings
│
└── chapters/
    ├── chapter1.tex         # Chapter 1: Introduction (~6 pages)
    ├── chapter2.tex         # Chapter 2: Literature Review & Problem Formulation (~8 pages)
    ├── chapter3.tex         # Chapter 3: System Methodology & Architecture (~8 pages)
    ├── chapter4.tex         # Chapter 4: Tools, Technologies & Implementation (~10 pages)
    ├── chapter5.tex         # Chapter 5: Results, Evaluation & GUI Walkthrough (~8 pages)
    └── chapter6.tex         # Chapter 6: Conclusion and Future Work (~3.5 pages)
```

---

## 📊 Estimated Page Count Breakdown (50–54 Pages Target)

| Section | Content | Estimated Pages |
| :--- | :--- | :---: |
| **Frontmatter** | Title Page, Declaration, Certificate, Abstract, TOC, LOF, LOT | **8 pages** |
| **Chapter 1** | Introduction, Motivation, Valorant Slang Nuances, Comparison Table | **6 pages** |
| **Chapter 2** | Literature Survey (15+ papers, 4-col table), Gap Analysis, Objectives | **8 pages** |
| **Chapter 3** | CRISP-DM Methodology, 5-Tier Architecture, Data Pipeline, EDA Charts | **8–9 pages** |
| **Chapter 4** | Math Formulations (TF-IDF, SVM, MNB, DistilBERT), Code, Engineering | **10–11 pages** |
| **Chapter 5** | Experimental Benchmarks, Bar Charts, Confusion Matrix, 4 GUI HUDs | **8 pages** |
| **Chapter 6** | Research Summary, Riot Studio Impact, Tournament Scouting, Future Work | **3.5 pages** |
| **References** | 20 Formal IEEE Citations | **2.5 pages** |
| **Annexures** | Plagiarism Certificate & Full Source Code Listings | **4–5 pages** |
| **TOTAL** | **Publication-Grade MCA Project Report** | **~52–54 Pages** |

---

## 🎨 Key Features & Zero-Dependency Vector Design

- **100% Vector Graphics:** All diagrams (System Architecture, Data Pipelines, CRISP-DM flowchart, KRMU University crest) are built with native `TikZ`.
- **Pure `pgfplots` Charts:** Dataset class distributions, Agent sentiment scores, and Benchmark comparisons render dynamically without needing external PNG/JPG files.
- **Zero Overflow Tables:** Built using `tabularx` with autowrapping `L`, `C`, `R` columns and clean `booktabs` borders.
- **Syntax-Highlighted Listings:** Full Python listings formatted using the `listings` package with custom `#F8F9FA` background and numbered lines.
- **Academic Standard:** Formatted in strict compliance with K.R. Mangalam University guidelines (`12pt`, Times New Roman, `1.5` line spacing, `left=1.25in, right=1in, top=1in, bottom=1in`).
