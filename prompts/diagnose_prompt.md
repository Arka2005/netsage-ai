---
prompt_version: v1.0
updated: 2026-08-20
notes: initial version — three worked examples (interface-down, ACL direction, abstain), per docs/ai_diagnosis_specification.md §3.3
---

Study the three worked examples below, then diagnose the case at the end in the same JSON
format. Return ONLY a JSON object — no prose, no markdown fences, no preamble.

---

## EXAMPLE 1 — reason from the lowest OSI layer first; a short, high-confidence answer

## CASE
case_id: NS-006

## SYMPTOM
Every host in VLAN 40 lost off-subnet connectivity at once after a maintenance window. Hosts still ping each other.

## TOPOLOGY NOTE
MLS1 is a layer-3 switch doing inter-VLAN routing with SVIs. VLAN 40 = 10.10.40.0/24, SVI 10.10.40.1.

## SHOW OUTPUT (this is your only evidence)
MLS1# show ip interface brief | include Vlan
Vlan1    unassigned    YES unset  administratively down down
Vlan10   10.10.10.1    YES manual up                    up
Vlan40   10.10.40.1    YES manual administratively down down

MLS1# show running-config interface Vlan40
interface Vlan40
 ip address 10.10.40.1 255.255.255.0
 shutdown

## DETERMINISTIC RULE FINDINGS (advisory — verify against the evidence yourself)
- R04_interface_down [HIGH]: Evidence shows an interface that is administratively down
  evidence: "Vlan40   10.10.40.1    YES manual administratively down down"

## TASK
Return the diagnosis JSON object.

## EXPECTED OUTPUT
{
  "case_id": "NS-006",
  "root_cause": "SVI Vlan40 was administratively shut down during the maintenance window, taking the whole subnet's routed gateway offline.",
  "root_cause_tag": "interface_shutdown",
  "osi_layer": "L3",
  "confidence": 0.9,
  "confidence_band": "high",
  "evidence": [
    {
      "quote": "Vlan40   10.10.40.1    YES manual administratively down down",
      "source": "show_outputs",
      "why": "The interface brief table shows Vlan40 administratively down — the SVI itself is disabled, not a routing or ACL problem."
    },
    {
      "quote": "shutdown",
      "source": "show_outputs",
      "why": "The running-config confirms a shutdown command is applied to Vlan40."
    }
  ],
  "next_command": ["show ip interface brief | include Vlan"],
  "fix_steps": ["Enter interface Vlan40 configuration mode", "Remove the shutdown command with 'no shutdown'"],
  "verification_steps": ["Re-check show ip interface brief for Vlan40 up/up", "Confirm hosts in VLAN 40 regain off-subnet connectivity"],
  "risk_notes": "None — re-enabling a previously working SVI is low risk.",
  "requires_human_review": true
}

---

## EXAMPLE 2 — reading ACL hit counters; the "(0 matches)" signal; a compound L3/L4 layer

## CASE
case_id: NS-021

## SYMPTOM
An ACL intended to stop Guest VLAN 30 from reaching the server VLAN has instead blocked all traffic from the server VLAN, including replies to Sales.

## TOPOLOGY NOTE
ACL 110 was written to deny 10.10.30.0/24 to 10.10.99.0/24 and was applied on R1 Gi0/0.99.

## SHOW OUTPUT (this is your only evidence)
R1# show access-lists 110
Extended IP access list 110
 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)
 20 permit ip any any (12 matches)

R1# show ip interface Gi0/0.99 | include access list
  Outgoing access list is not set
  Inbound  access list is 110

PC-GUEST> ping 10.10.99.20
Reply from 10.10.99.20: bytes=32 time=3ms TTL=127

## DETERMINISTIC RULE FINDINGS (advisory — verify against the evidence yourself)
- R11_acl_zero_match [HIGH]: ACL 110 has a permit/deny line with 0 matches but is the stated intent
  evidence: "10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)"
- R11_acl_zero_match [INFO]: ACL 110 is applied inbound — verify this is the intended direction/interface
  evidence: "Inbound  access list is 110"

## TASK
Return the diagnosis JSON object.

## EXPECTED OUTPUT
{
  "case_id": "NS-021",
  "root_cause": "ACL 110 is applied inbound on the server subinterface, so it never sees guest-sourced traffic — the deny line has 0 matches because traffic never arrives from the direction the ACL is watching.",
  "root_cause_tag": "acl_wrong_direction",
  "osi_layer": "L3/L4",
  "confidence": 0.82,
  "confidence_band": "high",
  "evidence": [
    {
      "quote": "10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)",
      "source": "show_outputs",
      "why": "The deny line never matches, meaning guest traffic never reaches it despite the successful guest ping."
    },
    {
      "quote": "Inbound  access list is 110",
      "source": "show_outputs",
      "why": "The ACL is bound inbound on the server-side subinterface, the wrong side to catch guest-sourced traffic."
    }
  ],
  "next_command": ["show ip interface Gi0/0.99 | include access list"],
  "fix_steps": ["Remove the ACL from Gi0/0.99", "Apply it inbound on Gi0/0.30 instead, closest to the source"],
  "verification_steps": ["Re-test from a guest host", "Confirm the deny line increments"],
  "risk_notes": "Applying it outbound on the server side would also filter return traffic to other VLANs.",
  "requires_human_review": true
}

---

## EXAMPLE 3 — abstaining on thin evidence; this is a correct answer, not a failure

## CASE
case_id: NS-990

## SYMPTOM
PC3 in the Ops area intermittently loses connectivity to the file server; it clears on its own after a few minutes with no changes made.

## TOPOLOGY NOTE
PC3 is on VLAN 40 (10.10.40.0/24), routed through MLS1 to the Servers VLAN (10.10.99.0/24).

## SHOW OUTPUT (this is your only evidence)
PC3> ping 10.10.99.20
Reply from 10.10.99.20: bytes=32 time=1ms TTL=126

PC3> ping 10.10.99.20
Request timed out.

PC3> ping 10.10.99.20
Reply from 10.10.99.20: bytes=32 time=118ms TTL=126

## DETERMINISTIC RULE FINDINGS (advisory — verify against the evidence yourself)
(none)

## TASK
Return the diagnosis JSON object.

## EXPECTED OUTPUT
{
  "case_id": "NS-990",
  "root_cause": "The evidence only shows an intermittent, self-clearing ping pattern with no interface, routing, ACL, or duplex signal to explain it — there isn't enough here to name a single root cause.",
  "root_cause_tag": "insufficient_evidence",
  "osi_layer": "L1/L2",
  "confidence": 0.2,
  "confidence_band": "low",
  "evidence": [],
  "next_command": ["show interfaces | include error", "show spanning-tree vlan 40", "show interfaces trunk"],
  "fix_steps": ["No fix yet — gather more evidence before proposing a change"],
  "verification_steps": ["Re-run the disambiguating commands above and re-diagnose once they return output"],
  "risk_notes": "Guessing a fix here risks masking an intermittent physical-layer issue (e.g. a flapping link or STP recalculation) rather than resolving it.",
  "requires_human_review": true
}

---

Now diagnose the following case in the same JSON format as the examples above.
