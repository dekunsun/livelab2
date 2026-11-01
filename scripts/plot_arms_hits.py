"""Poster figure: onsets located within ±120 s at t2, K = 1,800, per arm, Opus 5.5 vs Gemini 3.1 Pro.

  ./.venv/bin/python scripts/plot_arms_hits.py   -> docs/figures/arms_hits.png
Counts are read from the result records, never typed in.
"""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
ARMS = [("F2_t2", "baselines", "Classical change\ndetection"), ("E_K1800_t2", None, "Fixed window\n(last 1,800 s)"),
        ("D_K1800_t2", None, "Agent chooses\nthe windows"), ("B_K1800_t2", None, "Oracle window\n(true onset)")]
MODELS = [("opus-5.5", "Claude Opus 5.5", "#011F5B"), ("gemini-3.1-pro", "Gemini 3.1 Pro", "#8a98b8")]


def hits(agent, cell):
    d = ROOT / "results" / agent / "main_public" / cell
    return sum(json.load(open(p))["metrics"]["exact"]["120"] == "hit" for p in d.glob("*.json")) if d.exists() else None


fig, ax = plt.subplots(figsize=(10, 5.2), dpi=200)
w = 0.36
for j, (agent, label, colour) in enumerate(MODELS):
    for i, (cell, special, _) in enumerate(ARMS):
        v = hits("baselines", cell) if special == "baselines" else hits(agent, cell)
        if special == "baselines" and j == 1:
            continue
        x = i + (j - 0.5) * w if special != "baselines" else i
        if v is None:
            continue
        ax.bar(x, v, w if special != "baselines" else w, color=colour if special != "baselines" else "#b8c0cc", label=label if i == 1 else None)
        ax.text(x, v + 0.5, str(v), ha="center", va="bottom", fontsize=13, fontweight="bold", color="#15201c")
ax.set_xticks(range(len(ARMS)))
ax.set_xticklabels([a[2] for a in ARMS], fontsize=12)
ax.set_ylim(0, 25); ax.set_yticks([0, 5, 10, 15, 20, 25])
ax.set_ylabel("Onsets located within ±120 s, of 25", fontsize=12)
ax.set_title("Where in time should the agent look? Asked late in the anomaly, budget 1,800 readings per channel", fontsize=13, loc="left")
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.legend(frameon=False, fontsize=12, loc="upper left")
fig.text(0.01, -0.02, "LiveLab 2.0 · real batch distillation plant, 25 public episodes · one run per cell (Opus: three runs, all 17) · classical detector is model-free",
         fontsize=9, color="#6f7b76")
fig.tight_layout()
out = ROOT / "docs/figures/arms_hits.png"; out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, bbox_inches="tight", facecolor="white")
print(out)
