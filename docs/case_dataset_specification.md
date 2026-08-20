# Case Dataset Specification — NetSage AI

The contract for `data/cases.csv`. This file is the project's centre of gravity: prompts read
from it, the rule engine reasons over it, and every accuracy number in the dashboard is measured
against it.

---

## 1. File facts

| Property | Value |
| --- | --- |
| Path | `data/cases.csv` |
| Format | RFC 4180 CSV, **every field quoted**, `LF` line endings |
| Encoding | UTF-8 |
| Header | Required, exact column order below |
| Multi-line fields | `show_outputs`, `topology_note`, `expected_fix_steps` may contain real newlines inside quotes |
| Rows | **36** (requirement: ≥ 30) [DR-01] |
| Columns | 15 |

Read it with a proper CSV parser (`csv.DictReader`, `pandas.read_csv`), never by splitting on
commas — the `show` output is full of commas and newlines.

---

## 2. Column contract

| # | Column | Type | Required | Sent to model? | Description |
| --- | --- | --- | --- | --- | --- |
| 1 | `case_id` | `NS-\d{3}` | ✔ | ✔ | Unique, stable, never reused or renumbered [DR-04] |
| 2 | `title` | string | ✔ | ✘ | Short human label for dashboards and review screens |
| 3 | `category` | enum | ✔ | ✘ | Fault family — used for coverage and per-category accuracy |
| 4 | `concept_tag` | kebab-case | ✔ | ✘ | Finer-grained teaching concept, e.g. `acl-rule-order` |
| 5 | `symptom` | string | ✔ | **✔** | What the user reports, in user language |
| 6 | `topology_note` | string | ✔ | **✔** | Addressing and roles needed to reason about the fault |
| 7 | `show_outputs` | multi-line string | ✔ | **✔** | Verbatim CLI evidence — the substrate for evidence grounding |
| 8 | `expected_fault` | string | ✔ | ✘ | Ground-truth explanation in prose |
| 9 | `expected_root_cause` | snake_case tag | ✔ | ✘ | Ground-truth tag scored for exact match |
| 10 | `osi_layer` | enum | ✔ | ✘ | Ground-truth layer |
| 11 | `severity` | enum | ✔ | ✘ | Business impact — drives dashboard severity mix |
| 12 | `expected_next_command` | string | ✔ | ✘ | The single most useful next command |
| 13 | `expected_fix_steps` | string | ✔ | ✘ | Verified remediation, written as CLI-ish prose |
| 14 | `source_lab` | filename | ✔ | ✘ | `.pkt` file the case came from |
| 15 | `difficulty` | enum | ✔ | ✘ | `Easy` / `Medium` / `Hard` |

### The prompt/ground-truth split [DR-06]

Only columns 1, 5, 6 and 7 ever reach the model. Columns 8–13 are the answer key. The loader
enforces this structurally via `Case.to_prompt_context()` vs `Case.ground_truth()` — it is not
left to prompt discipline, because prompt discipline eventually fails.

---

## 3. Controlled vocabularies

### `category`

`VLAN` · `Gateway` · `DHCP` · `DNS` · `Routing` · `ACL` · `NAT` · `Wireless` · `Switching` · `Physical`

### `osi_layer`

`L1` · `L1/L2` · `L2` · `L2/L3` · `L3` · `L3/L4` · `L4` · `L4/L7` · `L7`

Compound tokens are allowed and intentional: an ACL fault genuinely spans L3 and L4, and forcing
a single layer would teach the wrong thing. Scoring treats a compound expectation as satisfied if
the model's answer overlaps it (see [`ai_diagnosis_specification.md`](ai_diagnosis_specification.md) §6).

### `severity`

| Value | Meaning |
| --- | --- |
| `Critical` | Whole site/segment down, or a security control has failed open |
| `High` | A whole VLAN, service or user group is broken |
| `Medium` | Single user or degraded-but-working |
| `Low` | Cosmetic or engineer-facing annoyance |

### `difficulty`

`Easy` — one obvious signal in the output · `Medium` — requires correlating two blocks ·
`Hard` — requires ruling out a plausible wrong answer.

### `expected_root_cause` tags

Snake_case, one tag per distinct fault mechanism. The dataset currently uses **36 unique tags**
(one per case, by design — no two cases share a mechanism). Adding a case means either reusing an
existing tag or adding a new one to this list.

```
vlan_wrong_access_assignment   vlan_not_defined              vlan_pruned_from_trunk
native_vlan_mismatch           host_wrong_default_gateway    interface_shutdown
duplicate_ip_address           wrong_subnet_mask             dhcp_relay_missing
dhcp_pool_exhausted            dhcp_wrong_default_router     rogue_dhcp_server
dns_client_not_configured      acl_blocks_dns                dns_record_missing
router_name_server_missing     missing_return_route          ospf_area_mismatch
ospf_wrong_wildcard            default_route_missing         acl_wrong_direction
acl_blocks_return_traffic      acl_rule_order                acl_wrong_interface
nat_missing_inside_interface   nat_acl_missing_subnet        nat_pool_exhausted
static_nat_wrong_inside_local  guest_isolation_missing       wireless_psk_mismatch
ap_uplink_not_trunk            dhcp_scope_missing            port_security_violation
duplex_mismatch                missing_clock_rate            stp_wrong_root_bridge
```

Plus one reserved non-fault tag the model may return: `insufficient_evidence` (abstain) [FR-12].

---

## 4. Current composition

**36 cases · 10 categories · 36 unique root-cause tags**

| Category | Cases | Case IDs |
| --- | --- | --- |
| VLAN | 4 | NS-001 … NS-004 |
| Gateway | 4 | NS-005 … NS-008 |
| DHCP | 4 | NS-009 … NS-012 |
| DNS | 4 | NS-013 … NS-016 |
| Routing | 4 | NS-017 … NS-020 |
| ACL | 4 | NS-021 … NS-024 |
| NAT | 4 | NS-025 … NS-028 |
| Wireless | 4 | NS-029 … NS-032 |
| Switching | 2 | NS-033, NS-036 |
| Physical | 2 | NS-034, NS-035 |

| Severity | Count | | OSI layer | Count | | Difficulty | Count |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Critical | 8 | | L1 | 1 | | Easy | 13 |
| High | 16 | | L1/L2 | 1 | | Medium | 16 |
| Medium | 11 | | L2 | 8 | | Hard | 7 |
| Low | 1 | | L2/L3 | 1 | | | |
| | | | L3 | 15 | | | |
| | | | L3/L4 | 5 | | | |
| | | | L4 | 1 | | | |
| | | | L4/L7 | 1 | | | |
| | | | L7 | 3 | | | |

All eight fault families named in the brief (VLAN, gateway, DHCP, DNS, routing, ACL, NAT,
wireless) have 4 cases each. `Switching` and `Physical` were added because several real Packet
Tracer failures (err-disable, duplex mismatch, missing clock rate, STP root placement) are
Layer 1/2 problems that an L3-only dataset would teach students to misattribute.

---

## 5. Worked example row

`NS-021` — chosen because it is the brief's own example scenario shape.

| Column | Value |
| --- | --- |
| `case_id` | `NS-021` |
| `title` | ACL applied in the wrong direction |
| `category` | `ACL` |
| `concept_tag` | `acl-direction` |
| `symptom` | An ACL intended to stop Guest VLAN 30 from reaching the server VLAN has instead blocked all traffic from the server VLAN, including replies to Sales. |
| `topology_note` | ACL 110 was written to deny 10.10.30.0/24 to 10.10.99.0/24 and was applied on R1 Gi0/0.99. |
| `show_outputs` | `R1# show access-lists 110` … `10 deny ip … (0 matches)` … `Inbound access list is 110` … guest ping succeeds |
| `expected_fault` | ACL 110 is applied inbound on the server subinterface, so it only sees traffic sourced from 10.10.99.0/24 and never matches guest traffic (0 matches on the deny line). |
| `expected_root_cause` | `acl_wrong_direction` |
| `osi_layer` | `L3/L4` |
| `severity` | `High` |
| `expected_next_command` | `show ip interface Gi0/0.99 \| include access list` |
| `expected_fix_steps` | Remove `ip access-group 110 in` from Gi0/0.99; apply inbound on Gi0/0.30 closest to the source; re-test and confirm the deny line increments. |
| `source_lab` | `lab-acl.pkt` |
| `difficulty` | `Medium` |

Note the two deliberate design touches: the `(0 matches)` counter is the proving evidence, and the
successful guest ping is the healthy control that rules out a routing fault.

---

## 6. Quality rules

Enforced by `netsage validate` where marked **[auto]**, otherwise by peer review.

1. **[auto]** `case_id` unique and matching `NS-\d{3}`.
2. **[auto]** No required field blank.
3. **[auto]** Enum fields (`category`, `osi_layer`, `severity`, `difficulty`) within vocabulary.
4. **[auto]** `expected_root_cause` in the tag list.
5. **[auto]** `show_outputs` at least 80 characters and containing at least one device prompt line — `<DEVICE># <command>` for IOS, or `<HOST># <command>` / `<HOST>> <command>` for hosts. Purely host-side cases (DNS client, addressing) legitimately contain no `#` prompt.
6. **[auto]** Warn when any brief-mandated family has fewer than 3 cases.
7. One injected fault per case. No compound faults.
8. `symptom` contains no diagnostic vocabulary — it must not name the fault.
9. `show_outputs` contains at least one healthy control line, so the model must discriminate.
10. `expected_fix_steps` has been verified to clear the symptom in Packet Tracer.
11. `expected_next_command` is a real command, and its output is present in or implied by the
    evidence.
12. No two cases share an `expected_root_cause` unless the mechanisms genuinely differ in context.

---

## 7. Extending the dataset

Adding cases is the highest-value improvement available to the team. Suggested next 12, ordered
by what would most improve coverage:

| Priority | Fault | Why |
| --- | --- | --- |
| 1 | Compound fault (wrong VLAN **and** missing route) | Tests whether the model reports both or fixates on one |
| 2 | Healthy case with no fault at all | Tests the abstain path — does it invent a problem? |
| 3 | MTU mismatch on a tunnel | Classic "ping works, transfers fail" discrimination |
| 4 | Asymmetric routing with an ACL on the return path | Punishes single-direction thinking |
| 5 | HSRP/VRRP misconfiguration | Common in real campus networks |
| 6 | Wrong VTP domain / mode | VLAN propagation failure that looks like a trunk fault |
| 7 | EtherChannel misconfig (mode mismatch) | Layer-2 bundle failure |
| 8 | DHCP snooping trusting the wrong port | Security control applied incorrectly |
| 9 | Overlapping subnets on two SVIs | Silent routing weirdness |
| 10 | Wrong NAT direction (`outside source` vs `inside source`) | Subtle NAT trap |
| 11 | Loopback advertised in the wrong OSPF area | Multi-area subtlety |
| 12 | Time/NTP drift breaking a time-based ACL | Non-obvious L7-adjacent cause |

Follow the checklist in
[`packet_tracer_integration.md`](packet_tracer_integration.md) §7 for each.
