# AI Diagnosis Specification — NetSage AI

The contract between NetSage AI and the language model: what goes in, what must come back, how it
is validated, and how it is scored.

---

## 1. Design stance

The model is treated as an **unreliable expert witness**. It is useful because it can read a wall
of CLI output and propose a hypothesis quickly. It is unreliable because it will produce a fluent,
confident answer whether or not the evidence supports one.

Three mechanisms hold it to account:

1. **Structural** — JSON-only output against a fixed schema. No prose to hide in.
2. **Evidential** — every claim must quote text that actually exists in the case. Quotes are
   verified by string matching, not by trusting the model.
3. **Human** — a person issues the verdict. Always. [HR-01]

---

## 2. Backend abstraction [AR-05]

One interface; the rest of the system is backend-blind.

```python
class LLMClient(Protocol):
    def complete(self, system: str, user: str, *, temperature: float = 0.0) -> LLMResponse: ...

@dataclass
class LLMResponse:
    text: str
    backend: str          # "ollama" | "api" | "mock"
    model: str
    temperature: float
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
```

| Backend | Transport | Use |
| --- | --- | --- |
| **`ollama`** *(default)* | `POST http://localhost:11434/api/chat`, `"stream": false`, `"format": "json"` | Primary. Offline, free, reproducible, no key. Suggested models: `llama3.1:8b`, `qwen2.5:7b`, `mistral:7b` |
| `api` | Hosted provider over HTTPS; key from `NETSAGE_API_KEY` env var only [NFR-05] | Optional quality comparison for the report |
| `mock` | Reads `tests/fixtures/responses/<case_id>.json` | CI, unit tests, and a network-free demo fallback [FR-11] |

Swapping backends must never change the schema, the validation or the scoring — only the numbers.
Running the same 36 cases through two backends and putting both columns in the dashboard is a
strong, cheap addition to the report.

### Sampling defaults [AR-07]

| Parameter | Value | Rationale |
| --- | --- | --- |
| `temperature` | `0.0` | Diagnosis is not creative; reproducibility is a requirement [NFR-04] |
| `top_p` | `1.0` | Left alone at temperature 0 |
| `max_tokens` | `1200` | Enough for a full diagnosis with evidence; caps runaway output |
| `format` | `json` (Ollama) | Structural pressure toward valid JSON |
| timeout | `120 s` | Local 7–8B models on CPU are slow |

---

## 3. Prompt library [AR-01, AR-02]

```
prompts/
├── system_prompt.md            role, constraints, safety rules
├── diagnose_prompt.md          the JSON contract + few-shot examples + case block
├── repair_prompt.md            one-shot "your JSON was invalid, here is the parser error"
└── followup_prompt.md          optional second turn once new show output is supplied
```

Each file carries YAML front-matter:

```yaml
---
prompt_version: v1.2
updated: 2026-08-20
notes: added ACL return-traffic worked example after NS-022 failure
---
```

`prompt_version` is stamped on every run record so a change in accuracy can be attributed to a
change in the prompt rather than guessed at. [AR-06]

### 3.1 System prompt — substance

- **Role.** A senior network engineer reviewing a junior's Packet Tracer lab.
- **Scope.** Cisco IOS-style campus networks: VLANs, trunking, STP, inter-VLAN routing, DHCP,
  DNS, static/OSPF routing, ACLs, NAT/PAT, wireless SSID-to-VLAN mapping, port security, physical
  layer.
- **Hard rules:**
  1. Output **one JSON object and nothing else** — no prose, no markdown fences, no preamble.
  2. Every `evidence[].quote` must be copied **character-for-character** from the supplied
     `show_outputs` or `symptom`. Never paraphrase a quote. Never invent output for a command
     that was not run.
  3. If the evidence does not support a single root cause, return
     `root_cause_tag: "insufficient_evidence"`, set `confidence ≤ 0.3`, and put the commands that
     *would* disambiguate in `next_command`. Abstaining is a correct answer, not a failure. [FR-12]
  4. Reason from the lowest OSI layer upward. Do not diagnose an ACL problem when an interface is
     `down/down`.
  5. `fix_steps` is advice for a human to read and decide on. Never phrase it as an action being
     taken. Never claim the problem is resolved.
  6. `requires_human_review` is always `true`.

### 3.2 User message layout

```
## CASE
case_id: NS-021

## SYMPTOM
<symptom>

## TOPOLOGY NOTE
<topology_note>

## SHOW OUTPUT (this is your only evidence)
<show_outputs>

## DETERMINISTIC RULE FINDINGS (advisory — verify against the evidence yourself)
- R11_acl_zero_match [HIGH]: ACL 110 line 10 has 0 matches
  evidence: " 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)"

## TASK
Return the diagnosis JSON object.
```

Rule findings are passed as *advisory*, deliberately worded so the model is not simply told the
answer. Whether including them helps or hurts is worth measuring: run the dataset with and
without the block and compare accuracy. That comparison is a good result to put in the report.

### 3.3 Few-shot examples [AR-02]

Three worked examples, chosen to teach three different behaviours:

| Example | Drawn from | Teaches |
| --- | --- | --- |
| 1 | NS-006-style (SVI `administratively down`) | Layer-1/2 first; short, high-confidence answer with one decisive quote |
| 2 | NS-021-style (ACL wrong direction) | Reading ACL hit counters; the `(0 matches)` signal; L3/L4 compound layer |
| 3 | A deliberately thin case | **Abstaining** — `insufficient_evidence`, low confidence, disambiguating commands |

Example 3 is the one most teams omit and the one that most improves behaviour. Without it, the
model learns that every prompt has an answer.

---

## 4. Response schema

```jsonc
{
  "case_id":        "string, echoes the input",
  "root_cause":     "string, 1–3 sentences of prose explanation",
  "root_cause_tag": "snake_case tag from the vocabulary, or insufficient_evidence",
  "osi_layer":      "one of L1|L1/L2|L2|L2/L3|L3|L3/L4|L4|L4/L7|L7",
  "confidence":     0.0,                    // float in [0,1]
  "confidence_band":"low|medium|high",      // low <0.4, medium 0.4–0.75, high >0.75
  "evidence": [
    {
      "quote":  "verbatim substring of show_outputs or symptom",
      "source": "show_outputs|symptom|topology_note",
      "why":    "one sentence: what this line proves"
    }
  ],
  "next_command":       ["show ...", "..."],   // 1–3, most useful first
  "fix_steps":          ["...", "..."],        // ordered, human-executable
  "verification_steps": ["...", "..."],        // how to prove it worked
  "risk_notes":         "string, side effects or what could go wrong",
  "requires_human_review": true                 // always true
}
```

**Field rules**

| Field | Constraint |
| --- | --- |
| `evidence` | 1–4 items. Empty is only valid when `root_cause_tag == "insufficient_evidence"` |
| `confidence` / `confidence_band` | Must agree with each other; mismatch is a validation error |
| `next_command` | 1–3 items, real Cisco IOS or host commands |
| `fix_steps` | 1–6 ordered steps; imperative mood; no "I have fixed" phrasing |
| extra keys | Rejected — unknown fields fail validation rather than being ignored |

---

## 5. Validation pipeline [C5]

```
raw text
  │
  ├─ strip markdown fences if present (models add them despite instructions)
  ├─ json.loads
  │    └─ fail → repair_prompt.md with the parser error → one retry → fail → status=parse_failed
  ├─ schema check: required keys, types, enums, no extra keys
  ├─ confidence/band consistency
  ├─ EVIDENCE GROUNDING  ← the important one
  │    for each evidence item:
  │       normalise whitespace on both sides
  │       assert quote is a substring of the declared source field
  │       on failure → flag hallucinated_evidence, keep the diagnosis, score it down
  ├─ tag check: root_cause_tag in vocabulary (unknown tag → flag unknown_tag)
  └─ post-check: does the tag contradict a HIGH rule finding? → flag rule_conflict
```

Whitespace normalisation collapses runs of spaces and trims line ends, so a model that reflows
indentation is not penalised — but a model that *invents* a line is caught. That distinction is
the entire point of the check.

**Statuses:** `ok` · `parse_failed` · `backend_error` · `schema_invalid`
**Flags:** `hallucinated_evidence` · `unknown_tag` · `rule_conflict` · `abstained` ·
`confidently_wrong`

---

## 6. Scoring [FR-05]

Per case, against ground truth the model never saw:

| Sub-score | Definition |
| --- | --- |
| `root_cause_match` | `root_cause_tag == expected_root_cause` (exact string) |
| `osi_match` | Layer token sets overlap — `L3/L4` vs `L4` counts as a match; `L2` vs `L7` does not |
| `next_command_match` | Normalised command (lowercased, whitespace-collapsed, pipe filter stripped) matches `expected_next_command`, or appears in the model's list |
| `evidence_grounded` | All evidence quotes verified present |
| `abstained` | Model returned `insufficient_evidence` |
| `confidently_wrong` | `confidence_band == "high"` **and** `root_cause_match == false` |

**Run-level metrics**

```
root_cause_accuracy  = root_cause_match / (total − abstained)
osi_accuracy         = osi_match        / (total − abstained)
grounding_rate       = evidence_grounded / total
abstain_rate         = abstained        / total
confidently_wrong    = count            (reported as a raw number, not a rate)
```

Abstentions are excluded from the accuracy denominator and reported separately. Otherwise a model
that refuses to answer looks identical to one that is wrong — and the two deserve very different
responses from the team.

**`confidently_wrong` is the headline safety metric.** A model that is wrong at low confidence is
an inconvenience; a model that is wrong at high confidence is what sends a junior engineer down a
20-minute dead end. Report it as a count, list every instance, and discuss it in the demo.

---

## 7. Run record (one JSONL line per case) [FR-07, AR-06]

```jsonc
{
  "run_id": "20260820T1130Z-ollama-llama3.1-8b-v1.2",
  "case_id": "NS-021",
  "timestamp_utc": "2026-08-20T11:30:14Z",
  "backend": "ollama", "model": "llama3.1:8b", "temperature": 0.0,
  "prompt_version": "v1.2",
  "rule_findings": [ { "rule_id": "R11_acl_zero_match", "severity": "HIGH", "message": "...", "evidence": "..." } ],
  "raw_response": "<verbatim model text>",
  "diagnosis": { /* validated schema object */ },
  "status": "ok",
  "flags": [],
  "scores": { "root_cause_match": true, "osi_match": true, "next_command_match": true,
              "evidence_grounded": true, "abstained": false, "confidently_wrong": false },
  "latency_ms": 8412,
  "review": null    // filled in later by `netsage review`
}
```

`raw_response` is stored verbatim, before any cleanup. When a result looks surprising, the raw
text is the only thing that settles the argument.

---

## 8. Known failure modes to expect

Documented up front so the team recognises them during review rather than rediscovering them.

| Failure mode | What it looks like | Countermeasure |
| --- | --- | --- |
| `plausible_but_unsupported` | A textbook-correct explanation that the evidence does not actually show | Evidence grounding + `why` field forcing a per-quote justification |
| `hallucinated_evidence` | Quotes a `show` line that was never supplied | Substring verification |
| `wrong_layer` | Diagnoses an ACL when an interface is `down/down` | "Lowest layer first" system rule; example 1 |
| `overconfident` | 0.9 confidence on a genuinely ambiguous case | Track `confidently_wrong`; tune the confidence rubric in the prompt |
| `should_have_abstained` | Invents a fault in a healthy case | Few-shot example 3; add healthy cases to the dataset |
| `incomplete_fix` | Correct root cause, fix that only half works | Reviewer checks `fix_steps` against `expected_fix_steps` |
| `fixates_on_first_signal` | Reports only the first anomaly in compound cases | Add compound cases (dataset spec §7) |
| `markdown_fence` | Wraps JSON in ```` ```json ```` despite instructions | Strip fences pre-parse; do not punish the model for it |

---

## 9. Prompt iteration protocol

Prompt engineering without a protocol is just guessing.

1. Never change a prompt and the dataset in the same commit.
2. Bump `prompt_version` on every change and note *why* in the front-matter.
3. Re-run the full 36 cases at temperature 0 on the same backend and model.
4. Record before/after for all five run-level metrics in a table in the report.
5. Keep a change that improves `root_cause_accuracy` **or** reduces `confidently_wrong` without
   worsening the other. Revert anything else.
6. Never tune a prompt against a single case. Fixing NS-022 while breaking three ACL cases is a
   net loss, and it is exactly what happens without step 3.
