# Research Evidence

Research evidence is the material needed to inspect what was requested,
what models returned, how trades settled, and how results were calculated.

| Category | Contents | Why retained |
|---|---|---|
| Raw LLM inputs/outputs | `llm_requests.jsonl`, `llm_calls.jsonl`, `provider_transport.jsonl`, `requests.jsonl`, `decision_inputs.jsonl`, sandbox `ledger.jsonl` | Actual prompts, replies, errors and delivery provenance |
| Market/account data | Prices, orders, trades, initial/closing accounts, cashflows, liquidity, agent outcomes and sandbox round records | Prices, fills, cash/shares and settlement |
| Configurations/protocols | YAML/JSON, protocols, source hashes, prepared-source ZIPs and personas | Conditions and implementations used |
| Scientific analyses | Reports, derived JSON/CSV, readouts, interpretation notes and figures | Complete results, exclusions and limits |
| Audits/reproduction receipts | Financial/input checks, replay reports, environment records and mismatch details | Check coverage, failures and exclusions |
| Incomplete/failed collection | DeepSeek continuation stages, R052, stopped wealth/forum roots and correction attempts | Missingness and request/cost history |
| Sealed archives | Existing evidence ZIPs, source archives and receipts | Immutable snapshots and reproduction dependencies |
| Existing replay outputs | Reproduced data and matching receipts | Previously verified matches, not additional observations |

[research_inventory.csv](research_inventory.csv) lists every immediate entry in
both `runs/` trees, including file counts, sizes, JSONL counts and visual counts.
Consult protocols/summaries/manifests for scientific status; names alone are insufficient.
