---
prompt_version: v1.1
updated: 2026-08-20
notes: rewrote examples 1 and 2 as fully synthetic cases (NS-991, NS-992) — v1.0 drew them verbatim from NS-006 and NS-021, which are live evaluation cases, so those two cases saw their own answer in the prompt. Teaching behaviour and lessons unchanged; evidence, devices, addressing and command output are all new.
---

Study the three worked examples below, then diagnose the case at the end in the same JSON
format. Return ONLY a JSON object — no prose, no markdown fences, no preamble.

---

## EXAMPLE 1 — reason from the lowest OSI layer first; a short, high-confidence answer

## CASE
case_id: NS-991

## SYMPTOM
Everyone at the Riverside branch says the intranet and the internet both stopped working this morning. People can still reach the printer and each other's machines.

## TOPOLOGY NOTE
RTR-BR2 is the branch router. Staff subnet is 172.20.5.0/24 with the gateway on RTR-BR2 Gi0/2 at 172.20.5.1. An outbound ACL 180 is applied on the branch WAN link.

## SHOW OUTPUT (this is your only evidence)
RTR-BR2# show ip interface brief
Interface              IP-Address      OK? Method Status                Protocol
GigabitEthernet0/1     198.51.100.6    YES manual up                    up
GigabitEthernet0/2     172.20.5.1      YES manual administratively down down
GigabitEthernet0/3     172.20.9.1      YES manual up                    up

RTR-BR2# show running-config interface Gi0/2
interface GigabitEthernet0/2
 description Riverside staff subnet
 ip address 172.20.5.1 255.255.255.0
 shutdown

RTR-BR2# show access-lists 180
Extended IP access list 180
 10 permit ip 172.20.5.0 0.0.0.255 any (0 matches)

## DETERMINISTIC RULE FINDINGS (advisory — verify against the evidence yourself)
- R04_interface_down [HIGH]: Evidence shows an interface that is administratively down
  evidence: "GigabitEthernet0/2     172.20.5.1      YES manual administratively down down"

## TASK
Return the diagnosis JSON object.

## EXPECTED OUTPUT
{
  "case_id": "NS-991",
  "root_cause": "The staff subnet's gateway interface Gi0/2 on RTR-BR2 is administratively shut down, so nothing on 172.20.5.0/24 can be routed off the local segment.",
  "root_cause_tag": "interface_shutdown",
  "osi_layer": "L3",
  "confidence": 0.91,
  "confidence_band": "high",
  "evidence": [
    {
      "quote": "GigabitEthernet0/2     172.20.5.1      YES manual administratively down down",
      "source": "show_outputs",
      "why": "The gateway interface for the affected subnet is administratively down while the other interfaces are up."
    },
    {
      "quote": "shutdown",
      "source": "show_outputs",
      "why": "The running-config confirms a shutdown command is applied to Gi0/2."
    }
  ],
  "next_command": ["show ip interface brief"],
  "fix_steps": ["Enter interface GigabitEthernet0/2 configuration mode on RTR-BR2", "Remove the shutdown command with 'no shutdown'"],
  "verification_steps": ["Re-check show ip interface brief for Gi0/2 up/up", "Confirm a staff host can reach the intranet again"],
  "risk_notes": "None — re-enabling a gateway interface that was previously working is low risk. Confirm the shutdown was not deliberate maintenance before reversing it.",
  "requires_human_review": true
}

Note the ACL 180 line also shows `(0 matches)`, which is tempting — but an ACL cannot match
traffic that never arrives, and the interface carrying that traffic is down. Resolve the
lower-layer fault first.

---

## EXAMPLE 2 — reading ACL hit counters; the "(0 matches)" signal; a compound L3/L4 layer

## CASE
case_id: NS-992

## SYMPTOM
A rule was added to stop the contractor wireless network from reaching the finance servers, but contractors can still open the finance intranet page. Finance staff report no problems of their own.

## TOPOLOGY NOTE
RTR-CORE routes between VLANs on subinterfaces. Contractors are VLAN 55 (192.168.55.0/24) on Gi0/3.55; finance servers are VLAN 77 (192.168.77.0/24) on Gi0/3.77. ACL 145 was written to deny 192.168.55.0/24 to 192.168.77.0/24.

## SHOW OUTPUT (this is your only evidence)
RTR-CORE# show access-lists 145
Extended IP access list 145
 10 deny ip 192.168.55.0 0.0.0.255 192.168.77.0 0.0.0.255 (0 matches)
 20 permit ip any any (2841 matches)

RTR-CORE# show ip interface Gi0/3.77 | include access list
  Outgoing access list is not set
  Inbound  access list is 145

PC-CONTRACTOR> ping 192.168.77.15
Reply from 192.168.77.15: bytes=32 time=2ms TTL=127

## DETERMINISTIC RULE FINDINGS (advisory — verify against the evidence yourself)
- R11_acl_zero_match [HIGH]: ACL 145 has a permit/deny line with 0 matches but is the stated intent
  evidence: "10 deny ip 192.168.55.0 0.0.0.255 192.168.77.0 0.0.0.255 (0 matches)"
- R11_acl_zero_match [INFO]: ACL 145 is applied inbound — verify this is the intended direction/interface
  evidence: "Inbound  access list is 145"

## TASK
Return the diagnosis JSON object.

## EXPECTED OUTPUT
{
  "case_id": "NS-992",
  "root_cause": "ACL 145 is applied inbound on the finance subinterface, so it only inspects traffic sourced from 192.168.77.0/24 and never sees contractor-sourced traffic — which is why the deny line has 0 matches while contractors still reach the servers.",
  "root_cause_tag": "acl_wrong_direction",
  "osi_layer": "L3/L4",
  "confidence": 0.84,
  "confidence_band": "high",
  "evidence": [
    {
      "quote": "10 deny ip 192.168.55.0 0.0.0.255 192.168.77.0 0.0.0.255 (0 matches)",
      "source": "show_outputs",
      "why": "The deny line never matches, so it is not filtering the contractor traffic it was written for."
    },
    {
      "quote": "Inbound  access list is 145",
      "source": "show_outputs",
      "why": "The ACL is bound inbound on the destination-side subinterface, the wrong side to catch contractor-sourced traffic."
    },
    {
      "quote": "Reply from 192.168.77.15: bytes=32 time=2ms TTL=127",
      "source": "show_outputs",
      "why": "Routing between the two VLANs works, which rules out a routing fault and isolates the problem to ACL placement."
    }
  ],
  "next_command": ["show ip interface Gi0/3.55 | include access list"],
  "fix_steps": ["Remove ip access-group 145 in from Gi0/3.77", "Apply it inbound on Gi0/3.55 instead, closest to the source"],
  "verification_steps": ["Re-test the finance intranet from a contractor host", "Confirm the deny line counter increments"],
  "risk_notes": "Applying the ACL outbound on the finance subinterface instead would also filter return traffic from other VLANs. Confirm no other subinterface relies on ACL 145 before moving it.",
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
