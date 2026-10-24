"""Generate Fig 3: 6-panel composite of scenario graph screenshots."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.image import imread

REPO = Path(__file__).resolve().parents[2]
screenshots_dir = REPO / "tests" / "scenarios" / "screenshots"
PANEL_ASPECT = 1.6  # every screenshot is centered in a 16:10 white frame

panels = [
    ("scenario-01-graph.png", "(a) Neurogenetics — 149 nodes"),
    ("scenario-02-graph.png", "(b) Oncology — 108 nodes"),
    ("scenario-03-graph.png", "(c) Rare Disease — 94 nodes"),
    ("scenario-04-graph.png", "(d) Immuno-Oncology — 132 nodes"),
    ("scenario-05-graph.png", "(e) CV/Inflammation — 94 nodes"),
    ("scenario-06-graph.png", "(f) GLP-1 CI — 206 nodes"),
]

fig, axes = plt.subplots(2, 3, figsize=(18, 8))
fig.patch.set_facecolor("white")

for idx, (fname, label) in enumerate(panels):
    row, col = divmod(idx, 3)
    ax = axes[row][col]
    img = imread(screenshots_dir / fname)
    h, w = img.shape[:2]
    # The screenshots come in different sizes; fit each inside the same
    # frame so every panel gets the same box.
    frame_w, frame_h = max(w, h * PANEL_ASPECT), max(h, w / PANEL_ASPECT)
    left, bottom = (frame_w - w) / 2, (frame_h - h) / 2
    ax.imshow(img, extent=(left, left + w, bottom, bottom + h))
    ax.set_xlim(0, frame_w)
    ax.set_ylim(0, frame_h)
    ax.set_title(label, fontsize=10, fontweight="bold", fontfamily="sans-serif", pad=8)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color("#dddddd")

plt.subplots_adjust(wspace=0.05, hspace=0.12)

out = REPO / "paper" / "figures" / "fig3-scenario-graphs.png"
fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
print(f"Saved → {out}")
