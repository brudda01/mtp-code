"""Plot the predeclared rule-only screen, preserving every condition and seed."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

report = json.loads(Path("runs/stage3_checks_20261102.json").read_text())
labels = ["skew_common", "skew_varied", "no_skew_common", "no_skew_varied"]
readable = [".02\nCommon", ".02\nVaried", "0\nCommon", "0\nVaried"]
plt.rcParams.update({"font.size": 11})
fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
for axis, key, scale, title in zip(
        axes, ["acf_returns_lag1", "mean_abs_mispricing", "mean_turnover_per_round"],
        [1, 100, 100], ["Lag-one return autocorrelation", "Mean absolute mispricing (%)",
                        "Turnover per round (% of shares)"]):
    means = [report["rule_summary"][label][key]["mean"] * scale for label in labels]
    stds = [report["rule_summary"][label][key]["sample_std"] * scale for label in labels]
    axis.bar(range(4), means, yerr=stds, capsize=4,
             color=["#416a9a", "#416a9a", "#d19036", "#d19036"], alpha=.75)
    for i, label in enumerate(labels):
        values = [r["metrics"][key] * scale for r in report["rule_runs"] if r["condition"] == label]
        axis.scatter(np.array([i] * 3) + np.array([-.12, 0, .12]), values,
                     color="black", s=23, zorder=3)
    axis.set_xticks(range(4), readable)
    axis.set_xlabel("Inventory skew / momentum horizons")
    axis.set_title(title)
    axis.grid(axis="y", alpha=.2)
fig.suptitle("Exploratory rule-only screen: 3 matched seeds x 1,000 rounds; dots are runs, bars mean +/- sample SD", fontsize=12)
fig.tight_layout()
for extension in ["png", "pdf"]:
    fig.savefig("runs/stage3_rule_sensitivity_20261102." + extension, dpi=160)
plt.close(fig)
Path("runs/stage3_plot_protocol.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
print("Saved labelled exploratory PNG/PDF and plot protocol")
