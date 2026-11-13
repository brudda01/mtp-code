"""Layout-only v2 of the response figure; keeps original data/artifacts intact."""
import argparse
import json
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.provenance import sha256,write_json


def render(report,output):
    report=Path(report);out=Path(output);out.mkdir(exist_ok=False)
    r=json.loads(report.read_text(encoding="utf-8"));cols=r["headline_contrasts"]
    assert len(cols)==8 and all(c["early3_available"] for c in cols)
    values=np.array([[c["actors"][aid]["executed_net"] for c in cols] for aid in ("llm_012","llm_013")]+[[c["combined_executed"] for c in cols]])
    limit=int(np.abs(values).max());fig,ax=plt.subplots(figsize=(12,4.2),layout="constrained")
    img=ax.imshow(values,cmap="RdBu_r",vmin=-limit,vmax=limit,aspect="auto")
    ax.set_yticks(range(3),["Meera","Arjun","Combined"])
    ax.set_xticks(range(8),[f"{c['seed']} / r{c['repetition']}\n{c['background']}" for c in cols],fontsize=8)
    for row in range(3):
        for col in range(8):ax.text(col,row,f"{values[row,col]:+d}",ha="center",va="center",color="white" if abs(values[row,col])>limit*.55 else "black",fontsize=11)
    fig.colorbar(img,ax=ax,label="Shares",shrink=.85)
    ax.set_title("Visible minus silent signed executions, rounds1-3\nAll eight comparisons: two scenarios, two model repeats, two MM backgrounds")
    fig.savefig(out/"executed_responses.png",dpi=180,bbox_inches="tight");fig.savefig(out/"executed_responses.pdf",bbox_inches="tight");plt.close(fig)
    shutil.copyfile(__file__,out/"figure_source.py")
    write_json(out/"data.json",dict(report_sha256=sha256(report),values=values.tolist(),columns=[{k:c[k] for k in ("seed","repetition","background")} for c in cols],note="Layout correction only: shorter colorbar label and tight bounding box. Original v1 plot/manifest retained. No outcome/data selection or new calls."))
    write_json(out/"artifact_manifest.json",{x.name:sha256(x) for x in out.iterdir() if x.is_file()})


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--report",required=True);parser.add_argument("--output",required=True);args=parser.parse_args();render(args.report,args.output)
