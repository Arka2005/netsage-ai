# Project Requirements — NetSage AI

Traceable requirements derived from [`problem_statement.md`](problem_statement.md).
Every requirement has an ID so specs, code and the demo can point back to it.

**ID scheme:** `FR-*` functional · `DR-*` data · `AR-*` AI/prompting · `HR-*` human oversight ·
`NFR-*` non-functional · `CON-*` constraint.

---

## 1. Scope

**In scope.** A local, offline-capable assistant that takes a Cisco-style lab troubleshooting
case (symptom + topology note + `show` command output), returns a structured diagnosis, checks
it against deterministic rules, requires a human verdict, and reports accuracy on a dashboard.

**Out of scope.** Live device access, config push/auto-remediation, real production networks,
SSH/Telnet automation, and any action that changes device state. NetSage AI **advises**; a human
**acts**.

---

## 2. Functional Requirements

| ID | Requirement | Priority | Source |
| --- | --- | --- | --- |
| FR-01 | Load and validate `data/cases.csv` into typed case objects, failing loudly on schema violations. | Must | Case dataset |
| FR-02 | Run a deterministic rule checker over each case **before** AI diagnosis (pre-check) and surface its findings. | Must | Rule checker |
| FR-03 | Send each case to an LLM using the prompt library and receive a JSON diagnosis that validates against the response schema. | Must | AI prompt library |
| FR-04 | Re-run the rule checker **after** diagnosis (post-check) to confirm the AI's claimed root cause is consistent with the evidence. | Should | Rule checker |
| FR-05 | Score each AI diagnosis against the case's ground truth (`expected_root_cause`, `osi_layer`, `expected_next_command`). | Must | Workflow step 4 |
| FR-06 | Present each scored diagnosis to a human reviewer and record a verdict of `Accepted`, `Edited` or `Rejected`. | Must | HR / workflow step 5 |
| FR-07 | Persist every run to an append-only artifact (`artifacts/runs/<run_id>.jsonl`) so results are reproducible and auditable. | Must | Deliverables |
| FR-08 | Generate a dashboard showing counts by issue type, counts by severity, and AI-vs-human agreement rate. | Must | Dashboard |
| FR-09 | Maintain a Responsible AI log containing at least 5 cases where a human corrected the AI, with a written reason. | Must | Responsible AI log |
| FR-10 | Support running a single case by ID for demo purposes (`--case NS-021`). | Must | Demo |
| FR-11 | Support a `mock` LLM backend so the whole pipeline runs with no network and no API key. | Should | NFR / grading |
| FR-12 | Allow the AI to **abstain** (`root_cause_tag: "insufficient_evidence"`) rather than guess when evidence is thin. | Should | Evidence use |

## 3. Data Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| DR-01 | At least 30 cases in `data/cases.csv`. Current count: **36**. | Must |
| DR-02 | Coverage of VLAN, gateway, DHCP, DNS, routing, ACL, NAT and wireless fault families, at minimum. | Must |
| DR-03 | Every case carries symptom, topology note, `show` outputs, expected fault, expected root-cause tag, OSI layer, concept tag and severity. | Must |
| DR-04 | `case_id` is unique and stable; cases are never renumbered once referenced by a run artifact. | Must |
| DR-05 | `show_outputs` must contain realistic, self-consistent CLI text — the evidence the AI is required to quote. | Must |
| DR-06 | Ground-truth fields are never sent to the model. They exist only for scoring. | Must |
| DR-07 | The dataset carries a mix of difficulty (`Easy` / `Medium` / `Hard`) so the accuracy number is meaningful. | Should |

Full column contract: [`case_dataset_specification.md`](case_dataset_specification.md).

## 4. AI & Prompting Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| AR-01 | Prompts must force JSON-only output with the fields `root_cause`, `confidence`, `evidence`, `next_command`, `fix_steps`. | Must |
| AR-02 | The prompt must include 2–3 worked few-shot examples drawn from real cases. | Must |
| AR-03 | Every item in `evidence[]` must quote a substring that actually appears in the case's `show_outputs` or `symptom`. Fabricated quotes are a scoring failure. | Must |
| AR-04 | `confidence` is a float in `[0.0, 1.0]` plus a band (`low` / `medium` / `high`), and must be lowered when evidence is missing. | Must |
| AR-05 | The LLM layer is provider-agnostic: one interface, adapters for **Ollama** (local, default), a hosted API, and a deterministic mock. | Must |
| AR-06 | Model, temperature, backend and prompt version are recorded with every run for reproducibility. | Must |
| AR-07 | Temperature defaults to `0.0`–`0.2`; diagnosis is not a creative task. | Should |
| AR-08 | Malformed JSON triggers one bounded repair retry, then the run is marked `parse_failed` — never silently patched. | Must |

Full contract: [`ai_diagnosis_specification.md`](ai_diagnosis_specification.md).

## 5. Human Oversight Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| HR-01 | No diagnosis is marked final without a human verdict. The default state is `Pending`. | Must |
| HR-02 | The reviewer sees the AI output, the rule-checker findings and the ground truth side by side before deciding. | Must |
| HR-03 | `Edited` and `Rejected` verdicts require a free-text reason; the reason field cannot be empty. | Must |
| HR-04 | Reviewer identity and a UTC timestamp are recorded on every verdict. | Must |
| HR-05 | The system never applies a fix, generates a config to paste, or claims a case is "resolved" on its own authority. | Must |
| HR-06 | At least 5 corrected cases are written up in `artifacts/responsible_ai_log.md` with a failure-mode category. | Must |

## 6. Non-Functional Requirements

| ID | Requirement |
| --- | --- |
| NFR-01 | Python 3.11+, standard library first; third-party dependencies pinned in `requirements.txt`. |
| NFR-02 | The full pipeline runs offline against local Ollama or the mock backend — no internet required for grading. |
| NFR-03 | A full 36-case run completes in under 10 minutes on a laptop with a local 7–8B model. |
| NFR-04 | Runs are reproducible: same case + same prompt version + same model + temperature 0 → same score. |
| NFR-05 | No secrets in the repo. API keys come from environment variables only; `.env` is git-ignored. |
| NFR-06 | Deterministic rule checks have unit tests with both a passing and a failing fixture. |
| NFR-07 | All artifacts are plain text (CSV / JSONL / Markdown) so they diff cleanly in Git. |

## 7. Constraints & Assumptions

| ID | Note |
| --- | --- |
| CON-01 | Team size 2–3 students; scope must be finishable in a semester project window. |
| CON-02 | Cases originate from Cisco Packet Tracer labs, not production equipment. |
| CON-03 | Packet Tracer has no API — `show` output is captured manually or via saved text. See [`packet_tracer_integration.md`](packet_tracer_integration.md). |
| CON-04 | LLM output is non-deterministic in general; grading assumes temperature 0 and accepts small wording variance. |
| CON-05 | The dataset is synthetic-but-realistic. Accuracy on it is an indicator, not a guarantee of real-world performance — this must be stated in the demo. |

## 8. Acceptance Criteria

Mapped directly to the brief's grading table.

| Grading check | Pass condition | Evidence to show |
| --- | --- | --- |
| Case coverage | ≥ 30 cases across multiple fault types | `data/cases.csv` — 36 cases, 10 categories |
| Evidence use | AI responses quote real `show` output | Evidence-grounding score in the dashboard; a failing example |
| Human oversight | Accepted / Edited / Rejected all present in the log | `artifacts/reviews.csv` |
| Deterministic checks | Checker catches basic config errors | Unit tests + sample checker output |
| Responsible AI | ≥ 5 documented corrections | `artifacts/responsible_ai_log.md` |

## 9. Requirement → Deliverable Traceability

| Brief deliverable | Requirements | Where it lives |
| --- | --- | --- |
| `cases.csv` | DR-01…DR-07 | `data/cases.csv` |
| Prompt files | AR-01…AR-04 | `prompts/diagnose_prompt.md` (+ helpers) |
| Python checker | FR-02, FR-04, NFR-06 | `src/netsage/rules/` |
| Dashboard | FR-08 | `src/netsage/dashboard/` → `artifacts/dashboard.html` |
| Responsible AI log | HR-06, FR-09 | `artifacts/responsible_ai_log.md` |
| Demo video | FR-10 | [`demo_plan.md`](demo_plan.md) |
