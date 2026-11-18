"""Generate model comparison and confusion-matrix figures from saved evaluation artifacts.

Always generates crisp zero-dependency SVG charts under research_graphs/ and results/.
When matplotlib is installed, also exports high-resolution (300 DPI) PNG counterparts.
"""

from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_FILE = RESULTS_DIR / "model_comparison.csv"
EVAL_JSON_FILE = RESULTS_DIR / "model_evaluation.json"
OUTPUT_DIR = PROJECT_ROOT / "research_graphs"

MODELS = (
    ("majority baseline", "Majority Baseline"),
    ("svm", "SVM"),
    ("naive bayes", "Naive Bayes"),
    ("lstm", "LSTM"),
    ("distilbert", "DistilBERT"),
    ("four-model ensemble", "Four-model Ensemble"),
)

METRICS = (
    ("accuracy", "Accuracy"),
    ("macro_precision", "Macro Precision"),
    ("macro_recall", "Macro Recall"),
    ("macro_f1", "Macro F1-score"),
    ("weighted_f1", "Weighted F1-score"),
)

ACC_COLORS = ("#577590", "#277DA1", "#43AA8B", "#90BE6D", "#F9C74F", "#F9844A")
METRIC_COLORS = ("#277DA1", "#43AA8B", "#F9C74F", "#F9844A", "#9B5DE5")


def load_evaluation_values() -> dict[str, dict[str, float]]:
    values: dict[str, dict[str, float]] = {}
    model_labels = dict(MODELS)
    required_columns = {"model", *(column for column, _ in METRICS)}

    with RESULTS_FILE.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
            raise ValueError(f"{RESULTS_FILE} is missing required evaluation columns.")

        for row in reader:
            source_name = row["model"].strip().casefold()
            if source_name not in model_labels:
                continue

            model_name = model_labels[source_name]
            if model_name in values:
                raise ValueError(f"Duplicate evaluation row for {model_name}.")

            values[model_name] = {}
            for column, label in METRICS:
                value = float(row[column])
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError(f"Invalid {label} value for {model_name}: {value}.")
                values[model_name][column] = value

    missing_models = [label for _, label in MODELS if label not in values]
    if missing_models:
        raise ValueError("Evaluation data is missing required models: " + ", ".join(missing_models))

    return values


def save_accuracy_svg(values: dict[str, dict[str, float]]) -> Path:
    width, height = 960, 520
    margin_l, margin_r, margin_t, margin_b = 75, 35, 70, 95
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b
    model_names = [label for _, label in MODELS]
    step = plot_w / len(model_names)
    bar_w = step * 0.62

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2:.1f}" y="38" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="20" font-weight="700" fill="#182026">Accuracy Comparison Across Models</text>',
    ]
    for tick in range(0, 101, 20):
        y = margin_t + plot_h * (1 - tick / 100.0)
        lines.append(f'<line x1="{margin_l}" y1="{y:.1f}" x2="{width - margin_r}" y2="{y:.1f}" stroke="#D9DEE5" stroke-width="1"/>')
        lines.append(f'<text x="{margin_l - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="Segoe UI, Arial, sans-serif" font-size="12" fill="#4A5568">{tick}%</text>')

    lines.append(f'<line x1="{margin_l}" y1="{margin_t + plot_h}" x2="{width - margin_r}" y2="{margin_t + plot_h}" stroke="#4A5568" stroke-width="1.2"/>')
    for idx, name in enumerate(model_names):
        acc = values[name]["accuracy"]
        x = margin_l + idx * step + (step - bar_w) / 2
        bar_h = plot_h * acc
        y = margin_t + plot_h - bar_h
        color = ACC_COLORS[idx % len(ACC_COLORS)]
        lines.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="3" fill="{color}"/>')
        lines.append(f'<text x="{x + bar_w / 2:.1f}" y="{y - 8:.1f}" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="12" font-weight="600" fill="#182026">{acc * 100:.1f}%</text>')
        lines.append(f'<text x="{x + bar_w / 2:.1f}" y="{margin_t + plot_h + 24:.1f}" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="11.5" fill="#2D3748">{html.escape(name)}</text>')

    lines.append("</svg>")
    out_path = OUTPUT_DIR / "model_accuracy_comparison.svg"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def save_metrics_svg(values: dict[str, dict[str, float]]) -> Path:
    width, height = 1120, 560
    margin_l, margin_r, margin_t, margin_b = 75, 35, 95, 95
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b
    model_names = [label for _, label in MODELS]
    group_step = plot_w / len(model_names)
    group_w = group_step * 0.80
    bar_w = group_w / len(METRICS)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2:.1f}" y="34" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="20" font-weight="700" fill="#182026">Model Performance Metrics Comparison</text>',
    ]
    legend_x = 180
    for m_idx, (_, label) in enumerate(METRICS):
        lx = legend_x + m_idx * 165
        lines.append(f'<rect x="{lx}" y="52" width="12" height="12" rx="2" fill="{METRIC_COLORS[m_idx]}"/>')
        lines.append(f'<text x="{lx + 18}" y="62" font-family="Segoe UI, Arial, sans-serif" font-size="12" fill="#2D3748">{html.escape(label)}</text>')

    for tick in range(0, 101, 20):
        y = margin_t + plot_h * (1 - tick / 100.0)
        lines.append(f'<line x1="{margin_l}" y1="{y:.1f}" x2="{width - margin_r}" y2="{y:.1f}" stroke="#D9DEE5" stroke-width="1"/>')
        lines.append(f'<text x="{margin_l - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="Segoe UI, Arial, sans-serif" font-size="12" fill="#4A5568">{tick}%</text>')

    lines.append(f'<line x1="{margin_l}" y1="{margin_t + plot_h}" x2="{width - margin_r}" y2="{margin_t + plot_h}" stroke="#4A5568" stroke-width="1.2"/>')
    for idx, name in enumerate(model_names):
        gx = margin_l + idx * group_step + (group_step - group_w) / 2
        for m_idx, (col, _) in enumerate(METRICS):
            val = values[name][col]
            x = gx + m_idx * bar_w
            bh = plot_h * val
            y = margin_t + plot_h - bh
            lines.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 2:.1f}" height="{bh:.1f}" rx="2" fill="{METRIC_COLORS[m_idx]}"/>')
            lines.append(f'<text x="{x + (bar_w - 2) / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="8.5" fill="#182026">{val * 100:.0f}%</text>')
        lines.append(f'<text x="{gx + group_w / 2:.1f}" y="{margin_t + plot_h + 24:.1f}" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="11.5" fill="#2D3748">{html.escape(name)}</text>')

    lines.append("</svg>")
    out_path = OUTPUT_DIR / "model_metrics_comparison.svg"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def save_confusion_matrices_svg() -> Path | None:
    if not EVAL_JSON_FILE.exists():
        return None
    data = json.loads(EVAL_JSON_FILE.read_text(encoding="utf-8"))
    labels = data.get("labels", ["Negative", "Neutral", "Positive"])
    models = list(data.get("models", {}).items())
    if not models:
        return None

    cols, cell = 3, 56
    rows = math.ceil(len(models) / cols)
    panel_w, panel_h = 280, 250
    width = cols * panel_w + 40
    height = rows * panel_h + 70

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2:.1f}" y="34" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="19" font-weight="700" fill="#182026">NLP Sentiment Confusion Matrices (Held-Out Test Set)</text>',
    ]
    for idx, (model_name, info) in enumerate(models):
        r, c = divmod(idx, cols)
        ox = 20 + c * panel_w + 68
        oy = 60 + r * panel_h + 36
        cm = info.get("confusion_matrix", [])
        acc = info.get("accuracy", 0.0) * 100
        max_val = max((v for row in cm for v in row), default=1) or 1
        lines.append(
            f'<text x="{ox + (len(labels) * cell) / 2:.1f}" y="{oy - 12}" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="12.5" font-weight="700" fill="#182026">{html.escape(model_name)} ({acc:.1f}%)</text>'
        )
        for i, row_vals in enumerate(cm):
            lines.append(f'<text x="{ox - 8}" y="{oy + i * cell + cell / 2 + 4:.1f}" text-anchor="end" font-family="Segoe UI, Arial, sans-serif" font-size="10.5" fill="#4A5568">{labels[i][:3]}</text>')
            for j, count in enumerate(row_vals):
                ratio = count / max_val
                shade = int(245 - ratio * 175)
                fill = f"rgb({shade}, {int(248 - ratio * 120)}, {int(255 - ratio * 70)})"
                text_fill = "#ffffff" if ratio > 0.55 else "#182026"
                x = ox + j * cell
                y = oy + i * cell
                lines.append(f'<rect x="{x}" y="{y}" width="{cell - 2}" height="{cell - 2}" rx="3" fill="{fill}" stroke="#CBD5E0"/>')
                lines.append(f'<text x="{x + (cell - 2) / 2:.1f}" y="{y + (cell - 2) / 2 + 5:.1f}" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="13" font-weight="600" fill="{text_fill}">{count}</text>')
        for j, lbl in enumerate(labels):
            lines.append(f'<text x="{ox + j * cell + (cell - 2) / 2:.1f}" y="{oy + len(labels) * cell + 16:.1f}" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="10.5" fill="#4A5568">{lbl[:3]}</text>')

    lines.append("</svg>")
    out_path = RESULTS_DIR / "nlp_confusion_matrices.svg"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def try_save_matplotlib_pngs(values: dict[str, dict[str, float]]) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import PercentFormatter
    except ImportError:
        return False

    model_names = [label for _, label in MODELS]
    accuracies = [values[name]["accuracy"] for name in model_names]
    fig, ax = plt.subplots(figsize=(11, 6.5), facecolor="white")
    bars = ax.bar(model_names, accuracies, color=ACC_COLORS, width=0.68, zorder=3)
    ax.bar_label(bars, labels=[f"{value:.1%}" for value in accuracies], padding=4, fontsize=9)
    ax.set_title("Accuracy Comparison Across Models", fontsize=16, pad=14, weight="bold")
    ax.set_ylabel("Accuracy", fontsize=11)
    ax.set_ylim(0, 1.1)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1))
    ax.grid(axis="y", color="#D9DEE5", linewidth=0.8, zorder=0)
    ax.tick_params(axis="x", labelrotation=18, labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(OUTPUT_DIR / "model_accuracy_comparison.png", dpi=300, facecolor="white", bbox_inches="tight")
    plt.close(fig)

    metric_count = len(METRICS)
    bar_width = 0.84 / metric_count
    centers = list(range(len(model_names)))
    fig, ax = plt.subplots(figsize=(13, 7), facecolor="white")
    for m_idx, (column, label) in enumerate(METRICS):
        positions = [c + (m_idx - (metric_count - 1) / 2) * bar_width for c in centers]
        metric_values = [values[name][column] for name in model_names]
        bars = ax.bar(positions, metric_values, width=bar_width * 0.92, color=METRIC_COLORS[m_idx], label=label, zorder=3)
        ax.bar_label(bars, labels=[f"{value:.1%}" for value in metric_values], padding=2, fontsize=6)
    ax.set_title("Model Performance Metrics", fontsize=16, pad=22, weight="bold")
    ax.set_ylabel("Score", fontsize=11)
    ax.set_ylim(0, 1.12)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1))
    ax.set_xticks(centers, model_names, rotation=18, ha="right", fontsize=9)
    ax.grid(axis="y", color="#D9DEE5", linewidth=0.8, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.2), ncol=5, frameon=False, fontsize=9)
    fig.savefig(OUTPUT_DIR / "model_metrics_comparison.png", dpi=300, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return True


def main() -> None:
    values = load_evaluation_values()
    OUTPUT_DIR.mkdir(exist_ok=True)
    acc_svg = save_accuracy_svg(values)
    met_svg = save_metrics_svg(values)
    cm_svg = save_confusion_matrices_svg()
    png_done = try_save_matplotlib_pngs(values)
    print(f"Generated SVG charts: {acc_svg.name}, {met_svg.name}" + (f", {cm_svg.name}" if cm_svg else ""))
    if png_done:
        print("Generated high-resolution PNG charts via matplotlib.")
    else:
        print("Skipped PNG export (matplotlib not installed); SVG charts are up to date.")


if __name__ == "__main__":
    main()
