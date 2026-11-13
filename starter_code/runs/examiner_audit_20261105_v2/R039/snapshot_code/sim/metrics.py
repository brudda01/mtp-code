"""Minimal stylized-facts metrics + plots. Extend fully per prompt P5
(Ljung-Box, GARCH via `arch`, Hurst, compare mode)."""
from __future__ import annotations
import argparse, json, os
import numpy as np
import pandas as pd


def acf(x: np.ndarray, nlags: int = 20) -> np.ndarray:
    x = x - x.mean()
    denom = (x * x).sum()
    return np.array([1.0] + [(x[:-k] * x[k:]).sum() / denom
                             for k in range(1, nlags + 1)])


def analyze(run_dir: str) -> dict:
    df = pd.read_csv(os.path.join(run_dir, "prices.csv"))
    p = df["price"].to_numpy(float)
    r = np.diff(np.log(p))
    r = r[np.isfinite(r)]
    n = len(r)
    out = {"rounds": int(df["round"].max()), "n_returns": n,
           "mean_return": float(r.mean()), "volatility": float(r.std())}
    if n > 20 and r.std() > 0:
        z = (r - r.mean()) / r.std()
        out["excess_kurtosis"] = float((z**4).mean() - 3)
        a_r, a_abs = acf(r, 10), acf(np.abs(r), 10)
        ci = 1.96 / np.sqrt(n)
        out["acf_returns_lag1"] = float(a_r[1])
        out["acf_abs_returns_lag1"] = float(a_abs[1])
        out["sig_acf_abs_lags_1_10"] = int((np.abs(a_abs[1:]) > ci).sum())
        vol_corr = pd.Series(df["volume"][1:].to_numpy(float)).corr(
            pd.Series(np.abs(r)), method="spearman")
        out["volume_absret_spearman"] = float(vol_corr)
        out["zero_volume_fraction"] = float((df["volume"] == 0).mean())
    json.dump(out, open(os.path.join(run_dir, "metrics.json"), "w"), indent=2)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        os.makedirs(os.path.join(run_dir, "plots"), exist_ok=True)
        fig, ax = plt.subplots(2, 1, figsize=(9, 6), sharex=True,
                               gridspec_kw={"height_ratios": [3, 1]})
        ax[0].plot(df["round"], df["price"], label="price")
        ax[0].plot(df["round"], df["fundamental"], "--",
                   label="fundamental", alpha=0.7)
        ax[0].legend(); ax[0].set_ylabel("price")
        ax[1].bar(df["round"], df["volume"], width=1.0)
        ax[1].set_ylabel("volume"); ax[1].set_xlabel("round")
        fig.tight_layout()
        fig.savefig(os.path.join(run_dir, "plots", "price.png"), dpi=120)
        plt.close(fig)
    except Exception as e:  # noqa: BLE001
        print("plotting skipped:", e)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    print(json.dumps(analyze(ap.parse_args().run_dir), indent=2))
