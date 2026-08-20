# `src/` — Implementation (planned)

No code yet. This file records the intended module layout and build order so implementation can
start without re-deriving the design. The authoritative design lives in
[`../docs/system_architecture.md`](../docs/system_architecture.md).

## Planned layout

```
src/
└── netsage/
    ├── __init__.py
    ├── cli.py                  validate | check | run | review | dashboard
    ├── cases.py                Case dataclass, CSV loader, schema validation
    │                           → to_prompt_context()  vs  ground_truth()   [the split that
    │                             keeps the answer key away from the model]
    ├── rules/
    │   ├── __init__.py         rule registry
    │   ├── base.py             Finding dataclass, check(case) -> list[Finding]
    │   ├── addressing.py       R01 duplicate_ip · R02 mask_mismatch · R03 gateway_mismatch
    │   │                       R09 apipa_address
    │   ├── layer2.py           R04 interface_down · R05 vlan_missing · R06 trunk_vlan_pruned
    │   │                       R07 native_vlan_mismatch · R13 duplex_mismatch
    │   ├── layer3.py           R08 route_missing · R14 ospf_area_mismatch
    │   └── services.py         R10 dhcp_relay_missing · R11 acl_zero_match · R12 nat_no_inside
    ├── ai/
    │   ├── client.py           LLMClient protocol + LLMResponse
    │   ├── ollama.py           default backend, localhost:11434, format=json
    │   ├── api.py              hosted adapter, key from env only
    │   ├── mock.py             fixture replay for CI and offline demo
    │   ├── prompts.py          template loading, {{placeholder}} render, prompt_version
    │   └── schema.py           JSON parse, schema check, EVIDENCE GROUNDING, repair retry
    ├── scoring.py              per-case sub-scores + run-level metrics
    ├── review/
    │   ├── cli.py              the human gate — Accept / Edit / Reject, resumable
    │   └── store.py            append-only artifacts/reviews.csv
    └── dashboard/
        ├── metrics.py          aggregate runs + reviews
        └── render.py           self-contained artifacts/dashboard.html + CSV export
```

Sibling directories created alongside `src/` during implementation:

```
prompts/       system_prompt.md · diagnose_prompt.md · repair_prompt.md · followup_prompt.md
artifacts/     runs/*.jsonl · reviews.csv · responsible_ai_log.md · dashboard.html
labs/          *.pkt baselines and broken/<case_id>.pkt
tests/         unit tests + fixtures/responses/ for the mock backend
```

## Build order

Each step ends with something demonstrable — no step depends on the LLM working.

| # | Step | Done when |
| --- | --- | --- |
| 1 | `cases.py` + `cli.py validate` | `netsage validate` prints the 36-case coverage summary |
| 2 | `rules/` + `cli.py check` | `netsage check --case NS-021` produces the findings in the functional spec |
| 3 | Unit tests for every rule | Each rule has a firing and a non-firing fixture (NFR-06) |
| 4 | `ai/mock.py` + `ai/schema.py` | Full pipeline runs end-to-end with zero network |
| 5 | `ai/ollama.py` + `prompts/` | `netsage run --backend ollama --all` completes |
| 6 | `scoring.py` | Run summary prints the five run-level metrics |
| 7 | `review/` | Accepted, Edited and Rejected all appear in `artifacts/reviews.csv` |
| 8 | `dashboard/` | `artifacts/dashboard.html` opens with all seven panels |
| 9 | Responsible AI log | ≥ 5 corrections written up with failure modes |

Steps 1–4 need no model at all. Getting through them first means the demo has a working fallback
before the LLM is ever in the critical path.

## Non-negotiables for whoever writes this

- Ground truth never enters a prompt. Enforce it in `cases.py`, not in prose.
- `requires_human_review` is hard-coded `true`. It is not a model output.
- Evidence quotes are verified by substring match against the case text. A quote that is not
  found is a flag, not a warning to ignore.
- Store `raw_response` verbatim before any cleanup.
- No secrets in the repo. Keys come from environment variables; `.env` stays git-ignored.
