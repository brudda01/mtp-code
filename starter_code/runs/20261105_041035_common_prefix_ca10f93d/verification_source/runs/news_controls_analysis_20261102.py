"""Audit preserved news controls and render an engineering diagnostic, no API."""
import hashlib
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.news_controls import CELLS, SEEDS, rows, verify
from sim.provenance import sha256, write_json

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "runs/20261102_191203_news_rule_controls_ca64e844"
report = json.loads((TARGET / "report.json").read_text())
assert report["status"] == "verified_rule_controls"
paths = {}
sources = []
cash_errors = []
for item in report["runs"]:
    path = TARGET / item["run_path"]
    paths[item["seed"], item["cell"]] = path
    manifest = json.loads((path / "manifest.json").read_text())
    assert sha256(path / "manifest.json") == item["manifest_sha256"]
    assert manifest["status"] == "completed" and manifest["completed_rounds"] == 600
    assert manifest["models"] == []
    assert sha256(path / "source.zip") == manifest["source_archive_sha256"]
    assert sha256(path / "config.yaml") == manifest["normalized_config_sha256"]
    for name, digest in manifest["output_sha256"].items():
        assert sha256(path / name) == digest, (path, name)
    for name, digest in manifest["source_sha256"].items():
        assert sha256(ROOT / name) == digest, (path, name, "source drift")
    sources.append(manifest["source_sha256"])
    summary = json.loads((path / "summary.json").read_text())
    cash_errors.append(summary["max_cash_conservation_error"])
assert all(source == sources[0] for source in sources)
for seed in SEEDS:
    check, metrics = verify({c: paths[seed, c] for c in CELLS}, seed)
    assert check == next(c for c in report["checks"] if c["seed"] == seed)
    assert metrics == [m for m in report["metrics"] if m["seed"] == seed]

fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True, constrained_layout=True)
for ax, seed in zip(axes, SEEDS):
    for cell, label, color in (("control", "Control = headline only", "#24619c"),
                               ("fundamentals_only", "Silent shift = combined", "#be5a19")):
        data = rows(paths[seed, cell] / "prices.csv")
        x = np.array([int(row["round"]) for row in data])
        price = np.array([float(row["price"]) for row in data])
        ax.plot(x, price, color=color, linewidth=.85, label=label)
    ax.plot([1, 600], [100, 100], color="#24619c", linestyle="--", alpha=.7,
            label="Control benchmark = 100")
    ax.plot([1, 300, 301, 600], [100, 100, 120, 120], color="#be5a19",
            linestyle="--", alpha=.7, label="Shift benchmark = 120 after event")
    ax.axvline(301, color="gray", linestyle=":", alpha=.7)
    ax.set_title(f"Seed {seed}", loc="left", fontsize=11)
    ax.set_ylabel("Auction price")
    ax.grid(alpha=.15)
axes[0].legend(fontsize=8, ncols=2, loc="upper left")
axes[-1].set_xlabel("Trading round (scheduled event at 301, payout after auction)")
fig.suptitle("Rule-only news controls: three matched seeds\n"
             "Each plotted path represents two financially identical cells; benchmark hidden from traders",
             fontsize=12)
fig.savefig(TARGET / "price_controls.png", dpi=180)
fig.savefig(TARGET / "price_controls.pdf")
plt.close(fig)

test_snapshot = TARGET / "test_news_controls.py"
shutil.copyfile(ROOT / "tests/test_news_controls.py", test_snapshot)
artifact_hashes = {p.name: sha256(p) for p in TARGET.iterdir()
                   if p.is_file() and p.name != "audit.json"}
regression = json.loads((ROOT / "runs/news_baseline_regression_20261102.json").read_text())
audit = dict(status="verified", run_count=12, rounds_per_run=600,
             model_requests=0, independent_exogenous_seeds=list(SEEDS),
             all_output_hashes_verified=True, all_source_hashes_verified=True,
             max_cash_conservation_error=max(cash_errors),
             source_parent=manifest["parent_revision"],
             working_tree_status=manifest["working_tree_status"],
             source_sha256=sources[0], baseline_regression=regression,
             artifact_sha256=artifact_hashes,
             analysis_source_sha256=sha256(Path(__file__)),
             interpretation="Engineering controls; not live-model behaviour or human realism. "
                            "Seed 633 drift retained. No defaults tuned or outcomes selected.")
write_json(TARGET / "audit.json", audit)
print(json.dumps({"audit": str(TARGET / "audit.json"), "run_count": 12,
                  "max_cash_conservation_error": max(cash_errors),
                  "price_figures": [str(TARGET / "price_controls.png"),
                                    str(TARGET / "price_controls.pdf")]}, indent=2))
