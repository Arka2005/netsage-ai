# NetSage AI

**An AI troubleshooting assistant for Cisco-style lab networks — with a human in the loop, always.**

Junior network engineers know the commands but struggle to connect a symptom to a root cause.
When a PC gets an IP address but cannot reach a server, is it VLAN, routing, DHCP, DNS, ACL or
NAT? NetSage AI reads the symptom, the topology note and the `show` command output, proposes a
likely fault with the evidence it used, names the OSI layer, suggests the next command — and then
stops. **A human reviewer approves, edits or rejects every single diagnosis.**

The system advises. It never touches a device.

---

## Status

| Area | State |
| --- | --- |
| Problem statement | ✅ Transcribed from the brief |
| Requirements & specs | ✅ 8 documents complete |
| Case dataset | ✅ **36 cases** across 10 fault families (requirement: ≥ 30) |
| Implementation (`src/`) | 🔜 Planned — see [`docs/system_architecture.md`](docs/system_architecture.md) |
| Prompts, artifacts, demo | 🔜 Planned |

---

## Repository layout

```
netsage-ai/
├── README.md
├── docs/
│   ├── problem_statement.md            the assignment brief, transcribed
│   ├── project_requirements.md         numbered, traceable requirements
│   ├── system_architecture.md          components, data flow, storage, tech choices
│   ├── functional_specification.md     command-by-command behaviour
│   ├── packet_tracer_integration.md    how labs become cases, and how fixes are verified
│   ├── case_dataset_specification.md   the cases.csv column contract
│   ├── ai_diagnosis_specification.md   prompt library, JSON schema, validation, scoring
│   └── demo_plan.md                    shot-by-shot script for the demo video
├── data/
│   └── cases.csv                       36 troubleshooting cases with ground truth
└── src/
    └── (see src/README.md for the planned module layout)
```

---

## How it works

```
Packet Tracer lab
      │  manual capture of show output
      ▼
  data/cases.csv ──▶ rule pre-check ──▶ AI diagnosis ──▶ validate + score
                     (deterministic)     (local LLM)      (evidence grounding)
                                                                │
                                                                ▼
                                                    ┌───────────────────────┐
                                                    │  HUMAN REVIEW (gate)  │
                                                    │  Accept / Edit /      │
                                                    │  Reject + reason      │
                                                    └───────────┬───────────┘
                                                                ▼
                                                     dashboard + audit trail
```

Five design commitments, in priority order:

1. **Deterministic first, probabilistic second.** Anything a Python function can prove is not
   left to an LLM. The rule checker runs before and after the model.
2. **Evidence or abstain.** Every claim must quote text that literally appears in the case's
   `show` output — verified by substring matching, not by trust. The model is explicitly allowed
   to answer `insufficient_evidence`.
3. **The human gate is a pipeline stage, not a feature.** No code path marks a case final without
   a verdict, and `Edited` / `Rejected` verdicts require a written reason.
4. **Advise, never act.** No SSH, no config push, no auto-remediation.
5. **Everything is replayable.** Model, temperature, prompt version and the raw response are
   stored with every run.

---

## The dataset

**36 cases · 10 categories · 36 distinct root-cause mechanisms**

| Category | Cases | | Category | Cases |
| --- | --- | --- | --- | --- |
| VLAN | 4 | | ACL | 4 |
| Gateway | 4 | | NAT | 4 |
| DHCP | 4 | | Wireless | 4 |
| DNS | 4 | | Switching | 2 |
| Routing | 4 | | Physical | 2 |

All eight fault families named in the brief have four cases each. `Switching` and `Physical` were
added because err-disabled ports, duplex mismatches, missing clock rates and STP root placement
are real Packet Tracer failures that an L3-only dataset would teach students to misattribute.

Each row carries a symptom in user language, a topology note, verbatim `show` output, and a
ground-truth answer key. **Only the symptom, topology note and `show` output are ever sent to the
model** — the split is enforced structurally, not by prompt discipline.

Full column contract: [`docs/case_dataset_specification.md`](docs/case_dataset_specification.md).

---

## Planned command surface

```bash
netsage validate                                    # schema-check the dataset
netsage check     --case NS-021                     # deterministic rules only, no LLM
netsage run       --backend ollama --model llama3.1:8b --all
netsage review    --run <run_id>                    # the human gate
netsage dashboard --run <run_id>                    # counts, accuracy, agreement rate
```

The LLM layer is provider-agnostic: **Ollama** (local, default, offline), a hosted API adapter,
and a deterministic mock so the whole pipeline runs in CI with no network and no API key.

Details: [`docs/functional_specification.md`](docs/functional_specification.md).

---

## Metrics that matter

| Metric | Why |
| --- | --- |
| Root-cause accuracy | Does it get the right answer? (abstentions excluded from the denominator) |
| Evidence grounding rate | Are the quotes real, or invented? |
| AI-vs-human agreement | `Accepted / (Accepted + Edited + Rejected)` |
| **Confidently wrong** | High confidence **and** wrong — the count that actually hurts a junior engineer |
| Abstain rate | Reported separately, because refusing to answer is not the same as being wrong |

---

## Deliverables map

| Brief deliverable | Where |
| --- | --- |
| `cases.csv` (≥ 30 cases) | `data/cases.csv` — 36 ✅ |
| Prompt files | `prompts/diagnose_prompt.md` (planned) |
| Python rule checker | `src/netsage/rules/` (planned) |
| Dashboard | `artifacts/dashboard.html` (planned) |
| Responsible AI log (≥ 5 corrections) | `artifacts/responsible_ai_log.md` (planned) |
| Demo video (5–10 min) | Script ready: [`docs/demo_plan.md`](docs/demo_plan.md) |

---

## Getting started

Right now the repo is documentation and data. To read it in the intended order:

1. [`docs/problem_statement.md`](docs/problem_statement.md) — what was asked for
2. [`docs/project_requirements.md`](docs/project_requirements.md) — what that means concretely
3. [`docs/system_architecture.md`](docs/system_architecture.md) — how it fits together
4. [`docs/ai_diagnosis_specification.md`](docs/ai_diagnosis_specification.md) — the model contract
5. [`data/cases.csv`](data/cases.csv) — open in a spreadsheet and read three rows

When implementation starts, `src/README.md` has the planned module layout and build order.

---

## Responsible AI

This project is as much about the limits of language models as their usefulness.

- The model is treated as an **unreliable expert witness**: fast at reading CLI output, and
  perfectly willing to produce a confident answer the evidence does not support.
- Hallucination is **measured, not hidden** — evidence grounding is a first-class dashboard metric.
- **Confidently wrong** is tracked separately from ordinarily wrong, listed by case, and discussed
  in the demo.
- The dataset is lab-derived and synthetic-but-realistic. Accuracy on it is an indicator, not a
  claim of production readiness, and the report says so.
- Nothing is ever applied automatically. A person types the fix.

---

*Project 2 — Applied AI + Network Troubleshooting. Team size 2–3.*
