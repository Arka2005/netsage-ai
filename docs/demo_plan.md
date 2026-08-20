# Demo Plan — NetSage AI

Script and shot list for the 5–10 minute demo video required by the brief.

**Target runtime: 8:00.** Under 5:00 fails the deliverable; over 10:00 gets cut off. Rehearse
with a timer at least twice.

---

## 1. What the assessor is looking for

The grading table maps almost one-to-one onto demo beats. Every beat below exists to satisfy a
specific row.

| Grading check | Demo beat |
| --- | --- |
| Case coverage | Beat 2 — dataset on screen, 36 cases, category breakdown |
| Evidence use | Beat 5 — AI output with quotes highlighted against the real `show` output |
| Human oversight | Beat 6 — a live Accept, and a live Reject with a typed reason |
| Deterministic checks | Beat 4 — rule checker run before the model |
| Responsible AI | Beat 7 — the log, plus one honest failure walked through |

If time runs short, cut Beat 3 (architecture) — never Beat 6 or 7.

---

## 2. Pre-flight checklist

Do all of this **before** hitting record.

- [ ] `netsage validate` passes cleanly
- [ ] A completed run exists and is fully reviewed — never review 36 cases live
- [ ] `artifacts/dashboard.html` is generated and open in a browser tab
- [ ] Ollama is running and the model is **already pulled and warmed** (`ollama run <model>` once
      so the first token is not a 40-second cold start)
- [ ] `--backend mock` verified as a working fallback if the model stalls on camera
- [ ] `labs/broken/NS-021.pkt` open in Packet Tracer, on the topology view
- [ ] A second clean Packet Tracer window ready for the fix
- [ ] Terminal font ≥ 16pt; window sized so `show` output does not wrap
- [ ] Desktop clean, notifications off, one browser tab per artifact
- [ ] Screen recorder at 1080p, microphone tested, room quiet
- [ ] Speaking roles assigned — see §5

---

## 3. Shot list

### Beat 1 — Framing (0:00 – 0:45)

*Screen: title slide, then the reference topology from `packet_tracer_integration.md`.*

> "A junior engineer knows the commands but not which one to run next. A PC has an IP address and
> still can't reach the server — is that VLAN, routing, DHCP, DNS, ACL or NAT? NetSage AI reads
> the symptom and the `show` output, proposes a root cause with the evidence it used, and then
> stops. A human decides. It never touches a device."

Say "it never touches a device" out loud. That sentence is the project's safety thesis.

---

### Beat 2 — The dataset (0:45 – 1:45)

*Screen: `data/cases.csv` in a spreadsheet, then `netsage validate` in the terminal.*

```
$ netsage validate
✔ 36 cases loaded from data/cases.csv
✔ schema OK — 15/15 columns
✔ coverage: VLAN 4 · Gateway 4 · DHCP 4 · DNS 4 · Routing 4 · ACL 4 · NAT 4 · Wireless 4 · Switching 2 · Physical 2
```

Points to make:

- 36 cases, all eight required fault families with four each, plus Switching and Physical.
- Scroll to one row and show the split: symptom, topology note and `show` output are what the
  model sees; the expected fault, tag, layer and fix are the answer key **and are never sent**.
- "That separation is why our accuracy number means something."

---

### Beat 3 — Architecture in 45 seconds (1:45 – 2:30)

*Screen: the pipeline diagram from `system_architecture.md`.*

Trace it with the cursor: ingest → rule pre-check → AI → validate → score → **human gate** →
dashboard.

> "Two things to notice. Deterministic checks run *before* the model — anything a Python function
> can prove, we don't ask an LLM. And the human gate is a stage in the pipeline, not a feature we
> added. There is no code path that marks a case final without a verdict."

*Cuttable if running long.*

---

### Beat 4 — The broken lab and the rule checker (2:30 – 4:00)

*Screen: Packet Tracer, `labs/broken/NS-021.pkt`.*

1. Click the guest PC → Desktop → Command Prompt.
2. `ping 10.10.99.20` → **succeeds**. Pause on it.
   > "That's the bug. The guest VLAN is supposed to be blocked from the server VLAN, and it
   > isn't. Nothing is down — a security control has failed open, which is worse than an outage
   > because nobody files a ticket."
3. Switch to R1 CLI, run `show access-lists 110`. Point at `(0 matches)` on the deny line.
4. Switch to the terminal:

```
$ netsage check --case NS-021
NS-021  ACL applied in the wrong direction   [ACL · High]
  R11_acl_zero_match  HIGH  ACL 110 line 10 has 0 matches but is the stated intent
      evidence: " 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)"
2 findings · 0 errors
```

> "No AI involved yet. That's twenty lines of Python. It can't tell us *why* the ACL isn't
> matching — but it proves that it isn't, and it will say the same thing every single time."

---

### Beat 5 — AI diagnosis (4:00 – 5:30)

*Screen: terminal.*

```
$ netsage run --backend ollama --model llama3.1:8b --case NS-021
```

While it runs, say what is happening: local model, no cloud, temperature zero, JSON-only contract.

Then walk the output:

```
NS-021  ACL applied in the wrong direction
  AI root cause : acl_wrong_direction              [expected: acl_wrong_direction]  ✔
  OSI layer     : L3/L4                            [expected: L3/L4]                ✔
  Confidence    : 0.82 (high)
  Evidence      : 2/2 quotes grounded                                               ✔
  Next command  : show ip interface Gi0/0.99 | include access list                  ✔
  Verdict       : PENDING HUMAN REVIEW
```

*Screen: split the terminal beside the Packet Tracer CLI window.*

> "This is the part I care about most. Every quote in the evidence block is checked as a literal
> substring of the `show` output we captured. Here's the model's quote — here's the same line in
> Packet Tracer. If it had invented that line, the run would be flagged `hallucinated_evidence`
> and scored down, no matter how good the answer sounded."

End the beat on the last line: **PENDING HUMAN REVIEW.**

---

### Beat 6 — Human review, both outcomes (5:30 – 7:00)

*Screen: `netsage review --run <run_id>`.*

**6a — Accept (~30 s).** NS-021. Reviewer reads the AI diagnosis, the rule findings and the
ground truth side by side, then presses `A`.

> "Correct, evidence-backed, and the fix is the one I'd apply. Accepted."

**6b — Reject (~60 s).** Jump to a case the model got wrong — NS-022 (implicit deny drops return
traffic) is the strongest choice.

> "Here it said `acl_blocks_dns`. Confidence 0.79 — high. It's wrong. It pattern-matched on a
> familiar ACL scenario and missed that the ACL has no permit for return traffic at all. Its
> evidence quotes are real, so grounding passes — but grounding doesn't make an answer correct.
> That's exactly why a human is in this loop."

Press `R`, type the reason live, select failure mode `plausible_but_unsupported`.

> "That reason is mandatory. You cannot reject a case in this tool without saying why, because
> the rejections are the dataset we learn from."

---

### Beat 7 — Fix, verify, and the Responsible AI log (7:00 – 8:00)

**Fix and verify (~35 s).** Back in Packet Tracer, apply the approved fix for NS-021 — **typed by
hand**, and say so:

```
R1(config)# interface Gi0/0.99
R1(config-subif)# no ip access-group 110 in
R1(config)# interface Gi0/0.30
R1(config-subif)# ip access-group 110 in
```

Guest PC → `ping 10.10.99.20` → **Request timed out.** Then `ping 8.8.8.8` → **succeeds.**

> "Guest is blocked from the servers and still has internet. And re-running the rule checker —
> silent. The finding is gone, which means we fixed the fault instead of masking it."

**Dashboard and log (~25 s).** Switch to `artifacts/dashboard.html`:

- counts by issue type and severity
- root-cause accuracy overall and per category
- AI-vs-human agreement rate
- evidence grounding rate
- **the confidently-wrong list**, in red

> "Three cases where it was confident and wrong. Those are the ones in our Responsible AI log —
> more than the five the brief asks for — each with the failure mode and what we changed in
> response."

Close on the log file, then:

> "The number that matters isn't the accuracy. It's that no diagnosis in this system ever reached
> a device without a person signing their name to it."

---

## 4. Recording notes

- **One take per beat**, not one take overall. Cutting between beats is fine and looks better.
- **Do not narrate typing.** Type, pause, then explain what is on screen.
- **Zoom terminal to ≥ 16pt.** Assessors often watch at reduced size.
- **If the model stalls on camera, cut and re-run with `--backend mock`.** A cached correct result
  is honest as long as you say "this is a cached run" — an eight-second dead-air pause is not.
- **Never fake a result.** If accuracy is 68%, say 68%. A demo that shows a real failure and a
  real correction scores better than one that shows nothing going wrong.
- Add captions or on-screen labels for each beat if editing time allows.

---

## 5. Roles

| Role | Owns | Speaks during |
| --- | --- | --- |
| **Narrator** | Framing and the closing line | Beats 1, 3, 7 |
| **Operator** | Terminal — validate, check, run, dashboard | Beats 2, 4, 5 |
| **Reviewer** | Review CLI and Packet Tracer fix | Beats 6, 7 |

For a two-person team, merge Narrator and Operator. Every member should speak at least once —
several rubrics award marks for it.

---

## 6. Fallback plan

| If | Then |
| --- | --- |
| Ollama fails to start | `--backend mock` with pre-recorded fixtures; state that on camera |
| The model returns a different (correct) answer than rehearsed | Fine — narrate what it actually said |
| The model gets NS-021 *wrong* on the day | **Even better.** Reject it live, then show a rehearsed correct case. A working human gate is the point of the project |
| Packet Tracer crashes | Reopen `labs/broken/NS-021.pkt`; keep a screen recording of Beat 4 as a spare clip |
| Recording overruns 10:00 | Cut Beat 3, then trim Beat 2 to the validate output only |

---

## 7. Post-demo submission bundle

- [ ] `demo.mp4` — 5–10 minutes, 1080p
- [ ] `data/cases.csv` — 36 cases
- [ ] `prompts/` — `diagnose_prompt.md` and helpers, with `prompt_version`
- [ ] `src/` — rule checker with tests, plus sample checker output
- [ ] `artifacts/dashboard.html` + CSV export
- [ ] `artifacts/reviews.csv` — with Accepted, Edited **and** Rejected all present
- [ ] `artifacts/responsible_ai_log.md` — ≥ 5 documented corrections
- [ ] `artifacts/runs/<run_id>.jsonl` — the audit trail
- [ ] `README.md` — setup and reproduction steps
