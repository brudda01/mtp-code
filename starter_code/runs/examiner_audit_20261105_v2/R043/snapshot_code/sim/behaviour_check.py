"""Prepare exact matched-state behavioural inputs; this command never calls an API."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid
import zipfile

import numpy as np

from sim.agents.base import Observation
from sim.agents.llm_agent import LLMAgent, PROMPT_VERSION
from sim.provenance import sha256, write_json


def cases():
    base = dict(name="Research Trader", age=35, occupation="accountant",
                risk_tolerance="medium", strategy_inclination="balanced", horizon="medium",
                backstory="You invest your personal savings in stocks and cash.", bias_clauses="")
    result=[]
    def add(case_id, family, factors, history, basis, persona):
        obs=Observation(9,30,history,20,.02,.0002,None,[],[],10000,100,basis,20000,[])
        agent=LLMAgent("research_000",10000,100,np.random.default_rng(0),
                       params={"condition":"A","memory_window":5,"max_tokens":4096}, persona=persona)
        messages=[{"role":"system","content":agent.system_prompt("KGP")},
                  {"role":"user","content":agent.user_prompt(obs)}]
        result.append(dict(case_id=case_id,family=family,factors=factors,
                           observation=asdict(obs),persona=persona,messages=messages,
                           messages_sha256=hashlib.sha256(json.dumps(messages,sort_keys=True).encode()).hexdigest()))
    for context,history in (("rising",[96,97,98,99,100]),("falling",[104,103,102,101,100])):
        for wording,risks in (("label",("low","high")),
                              ("description",("cautious about investment risk","comfortable with investment risk"))):
            for level,risk in zip(("low","high"),risks):
                add(f"risk_{context}_{wording}_{level}","risk",dict(context=context,wording=wording,risk=level),
                    history,100,{**base,"risk_tolerance":risk})
    clauses={"pain":"You find losses more painful than gains of the same size.",
             "weight":"Experiencing a loss weighs more heavily on you than an equally large gain."}
    for wording,clause in clauses.items():
        for framing,basis in (("gain",80),("loss",120)):
            for trait in ("neutral","loss_sensitive"):
                add(f"basis_{wording}_{framing}_{trait}","gain_loss",
                    dict(wording=wording,account_basis=framing,trait=trait),[100]*5,basis,
                    {**base,"bias_clauses":clause if trait == "loss_sensitive" else ""})
    return result


def prepare(output_root="runs"):
    root=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"behaviour_inputs_"+uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    source=Path(__file__).resolve().parent
    with zipfile.ZipFile(root/"source.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*.py")):
            archive.write(path,"sim/"+path.relative_to(source).as_posix())
    revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=source,text=True).strip()
    dirty=subprocess.check_output(["git","status","--short"],cwd=source,text=True).splitlines()
    inputs=cases()
    schedule=[]
    for repetition in (1,2,3):
        # Reverse paired order in the middle repeat. Provider draws remain uncontrolled.
        ordered=inputs if repetition != 2 else list(reversed(inputs))
        schedule.extend(dict(case_id=c["case_id"],repetition=repetition) for c in ordered)
    write_json(root/"battery.json",dict(version="matched_trait_states_v1",status="prepared_not_run",
        parent_revision=revision,working_tree_status=dirty,prompt_suite_version=PROMPT_VERSION,
        source_archive_sha256=sha256(root/"source.zip"),cases=inputs,schedule=schedule,
        proposed_profile=dict(provider="BharatCode",model="qwen-3.8-27b",temperature=.3,
                              reasoning_effort="low",max_tokens=4096,timeout_seconds=180),
        planned_decisions=48,maximum_attempts=96,
        interpretation="Synthetic matched-state probes, not executed history or human validation. Risk cases vary one risk field. Gain/loss cases cross acquisition basis with loss-sensitive clause; equal current wealth/resources. Neutral wording duplicates remain explicit. No news or hidden benchmark is supplied. Do not infer disposition from reasoning or a single HOLD; analyse signed requested/accepted exposure, basis-by-trait interaction and wording/context stability. No execution claim without an auction fixture. Independent fresh model repeats, not cached answers.",
        scoring="No uniquely profitable/correct direction. Compare all cases/repeats; report feasibility, failures, risk contrasts and gain/loss-by-trait interaction separately. This does not qualify mechanics again."))
    print(f"prepared 16 cases / 48 scheduled decisions, no API calls -> {root}")
    return root


if __name__ == "__main__":
    prepare()
