# Packet Tracer Integration — NetSage AI

How lab scenarios in Cisco Packet Tracer become rows in `data/cases.csv`, and how a fix gets
verified back in the simulator.

---

## 1. The constraint that shapes everything

Packet Tracer has **no public API, no SSH-scriptable device access, and a proprietary binary
`.pkt` format.** There is no supported way to programmatically pull `show` output from a running
topology. [CON-03]

So NetSage AI does not integrate with Packet Tracer as software. It integrates through a
**disciplined manual capture workflow**: a human breaks a lab, records the evidence in a fixed
format, and stores it as text. The simulator is the case *source* and the fix *verification
environment*; the pipeline itself only ever reads text files.

Being honest about this in the report is worth more marks than pretending an integration exists.

---

## 2. Lab environment

| Item | Value |
| --- | --- |
| Simulator | Cisco Packet Tracer 8.2.2 (9.0.0 also acceptable — record which one per lab) |
| Base topology files | `labs/*.pkt`, one per fault family |
| Naming | `lab-<family>.pkt`, e.g. `lab-acl.pkt`, `lab-nat.pkt`, `lab-wireless.pkt` |
| Recorded in the dataset | The `source_lab` column of each case |

### Reference topology

Most cases are built on one shared campus topology so evidence stays consistent across cases:

```
                    INTERNET (8.8.8.8 sim)
                          │
                    ISP  203.0.113.1/30
                          │ Gi0/1
                       ┌──┴──┐
                       │ R1  │  edge router · NAT/PAT · router-on-a-stick
                       └──┬──┘  Gi0/0.10 .20 .30 .99
                          │ trunk
                    ┌─────┴─────┐
                    │  SW1      │  access layer
                    └──┬──┬──┬──┘
                       │  │  └────── Fa0/20 → AP1 (CORP vlan20 / GUEST vlan30)
                       │  └───────── SW2 (trunk Gi0/1)
                       └──────────── PCs
   Serial 192.168.100.0/30 ── R2 (Branch, 172.16.50.0/24)
   Serial 192.168.200.0/30 ── R3 (OSPF peer, 172.16.60.0/24)
   MLS1 (L3 switch, SVIs for VLAN 40 / 50)

   VLAN 10 SALES   10.10.10.0/24  gw .1
   VLAN 20 ENG     10.10.20.0/24  gw .1
   VLAN 30 GUEST   10.10.30.0/24  gw .1
   VLAN 40 OPS     10.10.40.0/24  gw .1   (SVI on MLS1)
   VLAN 50 WLAN    10.10.50.0/24  gw .1   (SVI on MLS1)
   VLAN 99 SERVERS 10.10.99.0/24  gw .1   DNS .53 · intranet .20 · files .25/.30
```

Keeping addressing stable across labs means the rule engine's checks (duplicate IP, gateway
mismatch, missing route) can be written once and reused.

---

## 3. Case authoring workflow

For each case:

1. **Start from a known-good lab.** Open the family `.pkt`, confirm end-to-end connectivity, and
   save it as the baseline.
2. **Inject exactly one fault.** One fault per case. Compound faults are a separate, later
   exercise — they make scoring ambiguous.
3. **Save the broken copy** as `labs/broken/<case_id>.pkt`, e.g. `labs/broken/NS-021.pkt`.
4. **Observe from the user's point of view.** Run the failing action from a PC (`ping`,
   `tracert`, `nslookup`, browser) and write the `symptom` the way a user would report it — not
   the way an engineer would diagnose it. *"PC gets an IP but can't reach the server"*, not
   *"ACL is misapplied"*.
5. **Capture evidence.** Run the `show` commands a competent engineer would run *next*, and paste
   the output verbatim (see §4).
6. **Record the ground truth** — expected fault, root-cause tag, OSI layer, next command, fix
   steps — into the CSV.
7. **Fix it in the simulator and verify** the symptom clears. If the fix in your `expected_fix_steps`
   does not actually resolve the lab, the row is wrong.
8. **Re-save the broken copy** so the demo can reproduce it on demand.

> **Rule of thumb for evidence:** include enough output to make the fault *provable*, plus one or
> two lines that are *healthy*, so the model has to discriminate rather than pattern-match on the
> only block of text present.

---

## 4. Capture conventions

These conventions are what make `show_outputs` machine-checkable by the evidence-grounding rule
[AR-03].

- **Verbatim.** Copy CLI text exactly, including the device prompt line
  (`R1# show ip route`) and spacing. Do not tidy alignment.
- **Prompt line included.** Every block starts with `<DEVICE># <command>`. This is how a reader —
  and the model — knows which device produced which evidence.
- **Blank line between blocks.** Separate each command's output from the next with one empty line.
- **Host commands too.** PC-side output (`ipconfig /all`, `ping`, `tracert`, `nslookup`,
  `arp -a`) counts as evidence and belongs in the same field, with the PC name as the prompt.
- **Trim, do not edit.** Long output may be shortened with `| include` / `| section` — use the
  real filter syntax so it is reproducible — but never reword a line.
- **Redact nothing.** Lab addresses are already private/documentation ranges.
- **Newlines are real.** In the CSV, `show_outputs` is a quoted multi-line field. Write it with
  actual line breaks; the loader preserves them.

### Standard command set by fault family

| Family | Capture at minimum |
| --- | --- |
| VLAN | `show vlan brief`, `show interfaces <if> switchport`, `show interfaces trunk`, host `ipconfig` |
| Gateway | `show ip interface brief`, `show running-config interface <if>`, host `ipconfig /all`, `ping` to gateway |
| DHCP | `show ip dhcp pool`, `show ip dhcp binding`, `show ip dhcp conflict`, `show run \| section dhcp`, host `ipconfig` |
| DNS | host `nslookup` (working + failing), `ping` by IP, `show run \| include domain` |
| Routing | `show ip route`, `show ip protocols`, `show ip ospf neighbor`, `show ip ospf interface brief`, `tracert` |
| ACL | `show access-lists` (with hit counters), `show ip interface <if> \| include access list` |
| NAT | `show ip nat translations`, `show ip nat statistics`, `show run \| include ip nat` |
| Wireless | `show dot11 associations`, AP `show run \| section ssid`, uplink `show interfaces <if> switchport`, client `ipconfig` |
| Switching | `show interfaces <if> status`, `show port-security interface <if>`, `show spanning-tree vlan <n>`, `show logging` |
| Physical | `show interfaces <if>` (error counters), `show controllers <if>`, `show interfaces status` |

**ACL hit counters matter.** `(0 matches)` on a line that ought to be matching is one of the
strongest diagnostic signals in the whole dataset — always capture counters, and run the failing
traffic first so the counters are meaningful.

---

## 5. Directory layout on disk

```
labs/
├── lab-vlan-basics.pkt
├── lab-trunking.pkt
├── lab-intervlan-routing.pkt
├── lab-dhcp.pkt
├── lab-dhcp-security.pkt
├── lab-dns.pkt
├── lab-static-routing.pkt
├── lab-ospf.pkt
├── lab-acl.pkt
├── lab-nat.pkt
├── lab-wireless.pkt
├── lab-port-security.pkt
├── lab-stp.pkt
├── lab-physical.pkt
├── lab-l3-switching.pkt
├── lab-addressing.pkt
├── lab-wan-edge.pkt
└── broken/
    ├── NS-001.pkt
    ├── NS-002.pkt
    └── ...
```

`.pkt` files are binary and do not diff. Keep them out of noisy commits, use Git LFS if the repo
grows past a few tens of megabytes, and treat `data/cases.csv` — not the `.pkt` files — as the
authoritative dataset.

---

## 6. Verification loop (used live in the demo)

```
 1. Open labs/broken/<case_id>.pkt        → reproduce the symptom from the PC
 2. netsage check --case <case_id>        → deterministic findings
 3. netsage run --case <case_id>          → AI diagnosis, still PENDING
 4. netsage review --run <run_id>         → human verdict + reason
 5. Apply the approved fix in Packet Tracer (typed by the human, never pasted from the model
    without reading it)
 6. Re-run the original failing test in the simulator → symptom cleared
 7. Re-run step 2 → the rule findings that fired should now be silent
```

Step 7 is the part teams usually skip. A fix that clears the symptom but leaves a rule firing
usually means the real fault was masked rather than resolved.

---

## 7. Adding a new case — checklist

- [ ] Exactly one injected fault
- [ ] Symptom written from the user's perspective, no diagnostic language
- [ ] Topology note gives addressing and roles needed to reason about the fault
- [ ] `show_outputs` includes the proving evidence **and** at least one healthy control line
- [ ] Every device prompt line present and verbatim
- [ ] `expected_root_cause` uses an existing tag, or the new tag is added to the tag list
- [ ] `expected_next_command` is a command that actually appears in, or would produce, the evidence
- [ ] `expected_fix_steps` verified to clear the symptom in the simulator
- [ ] `severity` and `difficulty` set honestly
- [ ] Broken `.pkt` saved as `labs/broken/<case_id>.pkt`
- [ ] `netsage validate` passes
- [ ] `netsage check --case <id>` produces sensible findings (or none, if no rule covers it)
