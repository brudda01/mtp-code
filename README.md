This repository contains the simulation codebase, trading agent implementations, saved experimental market data, numerical analyses, and figures supporting thesis.

## Repository Overview

| Directory / File | Description |
|---|---|
| [`starter_code/`](starter_code/) | Core call-auction market simulator (`sim/`), simulation configurations (`configs/`), automated test suite (`tests/`), and saved experimental runs (`runs/`). |
| [`starter_code/sim/`](starter_code/sim/) | Market clearing mechanics, order book allocation, LLM and rule-based trader agents, dividend processes, and evaluation metrics. |
| [`sandbox_experiments/`](sandbox_experiments/) | Extended 100-round market experiments, wealth distribution studies, and heterogeneous opinion-feed dynamics. |
| [`visual_analysis/`](visual_analysis/) | Plotting scripts (`build_figures.py`, `build_comparison_figures.py`) and generated publication figures (`figures/`). |
| [`RESEARCH_EVIDENCE.md`](RESEARCH_EVIDENCE.md) | Guide to retained empirical data, raw LLM request/response logs, and accounting records. |
| [`research_inventory.csv`](research_inventory.csv) | Directory-by-directory inventory of preserved experiment runs and file counts. |

## Environment & Dependencies

Dependencies are listed in [`starter_code/requirements.txt`](starter_code/requirements.txt). To install:

```bash
pip install -r starter_code/requirements.txt
```

Core dependencies include:
- `numpy >= 1.26`
- `pandas >= 2.0`
- `pyyaml >= 6.0`
- `matplotlib >= 3.8`
- `pytest >= 8.0`
