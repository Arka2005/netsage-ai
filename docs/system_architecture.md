# System Architecture — NetSage AI

How the pieces fit together, what each one owns, and where the human sits in the loop.

---

## 1. Architectural principles

1. **Deterministic first, probabilistic second.** Rule checks run before and after the model.
   Anything a `for` loop can prove is not left to an LLM.
2. **Evidence or abstain.** A diagnosis that cannot quote the `show` output it relied on is not
   a diagnosis. The model is allowed to say "insufficient evidence".
3. **The human is a required stage, not a feature.** The pipeline has no path that marks a case
   final without a verdict.
4. **Advise, never act.** NetSage AI emits text. It does not touch devices.
5. **Everything is replayable.** Prompt version, model, temperature and raw response are stored
   with every run, so any number in the dashboard can be traced back to a specific artifact.

---

## 2. High-level view

```
                        ┌──────────────────────────┐
                        │  Cisco Packet Tracer     │
                        │  lab .pkt scenarios      │
                        └───────────┬──────────────┘
                                    │  manual capture of show output
                                    ▼
                        ┌──────────────────────────┐
                        │   data/cases.csv         │   ground truth lives here,
                        │   36 cases, 15 columns   │   and is never sent to the model
                        └───────────┬──────────────┘
                                    │
                                    ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │                        NetSage Pipeline                            │
   │                                                                    │
   │  ┌───────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐  │
   │  │ 1 Ingest  │──▶│ 2 Rule     │──▶│ 3 AI       │──▶│ 4 Post-    │  │
   │  │  + parse  │   │   pre-check│   │  diagnose  │   │   check    │  │
   │  └───────────┘   └────────────┘   └─────┬──────┘   └─────┬──────┘  │
   │                                         │                │         │
   │                                   ┌─────▼──────┐   ┌─────▼──────┐  │
   │                                   │ LLM        │   │ 5 Score vs │  │
   │                                   │ adapter    │   │  ground    │  │
   │                                   │ (ollama /  │   │  truth     │  │
   │                                   │  api/mock) │   └─────┬──────┘  │
   │                                   └────────────┘         │         │
   └──────────────────────────────────────────────────────────┼─────────┘
                                                              ▼
                                              ┌───────────────────────────┐
                                              │  6 HUMAN REVIEW  (gate)   │
                                              │  Accepted / Edited /      │
                                              │  Rejected + reason        │
                                              └───────────┬───────────────┘
                                                          ▼
                    ┌──────────────────────┬──────────────────────────────┐
                    │ artifacts/runs/*.jsonl│ artifacts/reviews.csv        │
                    │ artifacts/responsible_ai_log.md                      │
                    └──────────────┬───────────────────────────────────────┘
                                   ▼
                    ┌──────────────────────────────────────┐
                    │  7 Dashboard — issue mix, severity,  │
                    │    AI-vs-human agreement, evidence   │
                    │    grounding rate                    │
                    └──────────────────────────────────────┘
```

---

## 3. Components

### C1 — Case store (`src/netsage/cases.py`)
Owns `data/cases.csv`. Parses rows into a `Case` dataclass, validates the schema (required
columns, enum values, unique IDs), and exposes filtering by category / severity / difficulty.
Critically, it produces **two views** of a case:

- `Case.to_prompt_context()` — symptom, topology note, `show` outputs only.
- `Case.ground_truth()` — expected fault, root-cause tag, OSI layer, next command, fix steps.

The prompt layer is only ever handed the first view. This separation is what makes the accuracy
number honest.

### C2 — Rule engine (`src/netsage/rules/`)
A registry of small, pure functions with the signature `check(case) -> list[Finding]`. Each
returns findings with `rule_id`, `severity`, `message` and the `evidence` line it fired on.
Planned checks, drawn from the brief plus the dataset:

| Rule ID | Detects |
| --- | --- |
| `R01_duplicate_ip` | The same IPv4 address on two devices / a host colliding with a gateway |
| `R02_mask_mismatch` | Host mask that puts its own default gateway off-subnet |
| `R03_gateway_mismatch` | Configured gateway not present on any router/SVI interface |
| `R04_interface_down` | `administratively down`, `up/down`, or `err-disabled` in the output |
| `R05_vlan_missing` | Access port referencing a VLAN absent from `show vlan brief` / marked `Inactive` |
| `R06_trunk_vlan_pruned` | VLAN missing from a trunk's allowed list on one side only |
| `R07_native_vlan_mismatch` | Different native VLAN on the two trunk ends |
| `R08_route_missing` | No route (and no gateway of last resort) toward the destination subnet |
| `R09_apipa_address` | `169.254.x.x` on a host — a DHCP path failure signal |
| `R10_dhcp_relay_missing` | Remote-subnet DHCP failure with no `ip helper-address` on the SVI/subif |
| `R11_acl_zero_match` | An ACL line with `0 matches` that the stated intent says should be matching |
| `R12_nat_no_inside` | `ip nat inside source ... overload` with an empty *Inside interfaces* list |
| `R13_duplex_mismatch` | CRC/input errors on one end and late collisions on the other |
| `R14_ospf_area_mismatch` | Different area IDs on the two ends of one link |

Rules are advisory input to the model *and* an independent cross-check of its answer. They never
override a human.

### C3 — Prompt library (`prompts/`)
Versioned Markdown templates with `{{placeholders}}`. `diagnose_prompt.md` is the primary
template: role, the JSON contract, the abstain rule, 2–3 worked examples, then the case block.
Prompt files carry a `prompt_version` in front-matter that is stamped onto every run.

### C4 — LLM adapter layer (`src/netsage/ai/`)
One interface, several backends — chosen at runtime with `--backend`.

```
LLMClient (protocol)
  .complete(system: str, user: str, *, temperature: float) -> LLMResponse
      ├── OllamaClient   POST http://localhost:11434/api/chat   (default, offline)
      ├── ApiClient      hosted provider, key from env only
      └── MockClient     replays fixtures; no network, used by CI and unit tests
```

`LLMResponse` carries the raw text plus `backend`, `model`, `temperature`, latency and token
counts. Downstream code never branches on which backend produced it.

### C5 — Response validator (`src/netsage/ai/schema.py`)
Parses the model's text into the diagnosis schema, rejects extra or missing fields, and — the
important part — verifies that every `evidence[].quote` is a genuine substring of the case's
`show_outputs` or `symptom`. A quote that is not present is flagged `hallucinated_evidence`.
One bounded repair retry on malformed JSON, then `parse_failed`.

### C6 — Scorer (`src/netsage/scoring.py`)
Compares diagnosis to ground truth and emits per-case sub-scores: root-cause tag match, OSI
layer match, next-command match, evidence grounding, and a confidence-calibration flag
(high confidence + wrong answer is called out separately — it is the worst failure mode).

### C7 — Review CLI (`src/netsage/review/`)
Walks a run's cases, prints AI diagnosis / rule findings / ground truth side by side, and
collects `Accepted` / `Edited` / `Rejected` plus a mandatory reason for the latter two. Appends
to `artifacts/reviews.csv`. Resumable — a partly reviewed run picks up where it stopped.

### C8 — Dashboard (`src/netsage/dashboard/`)
Reads runs + reviews and renders a single self-contained `artifacts/dashboard.html`: counts by
category and severity, accuracy by category and difficulty, AI-vs-human agreement, evidence
grounding rate, and the confidently-wrong list. A CSV export backs it for the spreadsheet
deliverable.

### C9 — CLI entry point (`src/netsage/cli.py`)
```
netsage validate                          # schema-check the dataset
netsage check   --case NS-021             # rule engine only, no LLM
netsage run     --backend ollama --model llama3.1:8b [--case NS-021] [--all]
netsage review  --run <run_id>            # human gate
netsage dashboard --run <run_id>
```

---

## 4. Data flow for one case

| # | Stage | Input | Output | Failure mode |
| --- | --- | --- | --- | --- |
| 1 | Ingest | CSV row | `Case` object | Schema error → abort run |
| 2 | Pre-check | `Case` | `list[Finding]` | Rule exception → logged, run continues |
| 3 | Prompt build | prompt context only | system + user strings | Missing placeholder → abort |
| 4 | LLM call | strings | raw text | Timeout / backend down → `backend_error` |
| 5 | Validate | raw text | `Diagnosis` | Bad JSON → 1 retry → `parse_failed` |
| 6 | Post-check | `Diagnosis` + `Case` | consistency flags | — |
| 7 | Score | `Diagnosis` + ground truth | sub-scores | — |
| 8 | Persist | everything above | one JSONL line | — |
| 9 | **Human review** | the JSONL line | verdict + reason | **No verdict → case stays `Pending`, excluded from "final" counts** |
| 10 | Aggregate | reviews + runs | dashboard | — |

---

## 5. Storage layout

```
data/cases.csv                        input dataset (ground truth included, never prompted)
prompts/*.md                          versioned prompt templates
artifacts/runs/<run_id>.jsonl         one line per case per run — the audit trail
artifacts/reviews.csv                 human verdicts, append-only
artifacts/responsible_ai_log.md       the ≥5 written-up corrections
artifacts/dashboard.html              generated report
```

`run_id` format: `<UTC-timestamp>-<backend>-<model>-<prompt_version>`, e.g.
`20260820T1130Z-ollama-llama3.1-8b-v1.2`.

---

## 6. Technology choices

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | Brief mandates a Python rule checker; team familiarity |
| LLM (default) | Local Ollama | Offline, free, reproducible, no key needed for grading |
| LLM (optional) | Hosted API adapter | Stronger reasoning for a quality comparison in the report |
| LLM (test) | Mock client | CI and unit tests run with zero network |
| Data format | CSV + JSONL + Markdown | Diff-friendly, opens in Excel for the spreadsheet deliverable |
| Dashboard | Self-contained HTML (+ CSV export) | Opens anywhere, embeds in the demo video, no server |
| Tests | `pytest` | Satisfies NFR-06 |

---

## 7. Security & responsible-AI boundaries

- **No device credentials anywhere.** The system reads text files; it never authenticates to a
  network device.
- **No auto-remediation.** `fix_steps` is prose for a human to read and decide on.
- **Ground-truth isolation.** Expected answers are structurally separated from prompt context so
  the model cannot be accidentally fed the answer.
- **Hallucination is measured, not hidden.** Evidence grounding is a first-class dashboard
  metric, and unquotable evidence is a scoring failure.
- **Confidently wrong is tracked separately** from ordinarily wrong, because overconfidence is
  what actually hurts a junior engineer.
- **Stated limits.** The dataset is lab-derived and synthetic-but-realistic; the report and demo
  must say so rather than implying production readiness.
