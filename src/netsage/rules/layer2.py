"""R04 interface_down · R05 vlan_missing · R06 trunk_vlan_pruned · R07 native_vlan_mismatch ·
R13 duplex_mismatch.

See docs/system_architecture.md §3 (C2).
"""

import re

from netsage.cases import Case
from netsage.rules.base import Finding, find_line, iter_device_blocks

_UP_DOWN = re.compile(r"(?im)^(\S+)\s+is\s+up,\s*line protocol is down")
_INACTIVE_VLAN = re.compile(r"(?im)Access Mode VLAN:\s*(\d+)\s*\(Inactive\)")
# "show interfaces trunk" prints a header line, then a data row whose last column is the vlan list.
_ALLOWED_VLANS = re.compile(r"(?im)Vlans allowed on trunk\s*\n\S+\s+([\d,\-]+)")
_NATIVE_VLAN_MISMATCH_LOG = re.compile(r"(?im)%CDP-4-NATIVE_VLAN_MISMATCH:.*")

# "1-4094" (or anything covering more than this many VLANs) means "no explicit restriction
# configured" — the Cisco default — not a real, deliberately curated allow-list.
_UNRESTRICTED_VLAN_COUNT = 100


def check(case: Case) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_check_interface_down(case))
    findings.extend(_check_vlan_missing(case))
    findings.extend(_check_trunk_vlan_pruned(case))
    findings.extend(_check_native_vlan_mismatch(case))
    findings.extend(_check_duplex_mismatch(case))
    return findings


def _check_interface_down(case: Case) -> list[Finding]:
    text = case.show_outputs
    findings = []
    for phrase in ("administratively down", "err-disable"):
        if phrase in text:
            findings.append(
                Finding(
                    rule_id="R04_interface_down",
                    severity="HIGH",
                    message=f"Evidence shows an interface that is {phrase}",
                    evidence=find_line(text, phrase),
                )
            )
    m = _UP_DOWN.search(text)
    if m:
        findings.append(
            Finding(
                rule_id="R04_interface_down",
                severity="HIGH",
                message=f"{m.group(1)} is up/down — line protocol is down",
                evidence=find_line(text, m.group(0)),
            )
        )
    return findings


def _check_vlan_missing(case: Case) -> list[Finding]:
    text = case.show_outputs
    m = _INACTIVE_VLAN.search(text)
    if not m:
        return []
    return [
        Finding(
            rule_id="R05_vlan_missing",
            severity="HIGH",
            message=f"Access port's VLAN {m.group(1)} is inactive — not defined in the VLAN database",
            evidence=find_line(text, m.group(0)),
        )
    ]


def _parse_vlan_list(raw: str) -> set[int]:
    vlans: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-")
            vlans.update(range(int(lo), int(hi) + 1))
        elif part.isdigit():
            vlans.add(int(part))
    return vlans


def _check_trunk_vlan_pruned(case: Case) -> list[Finding]:
    per_device: dict[str, tuple[set[int], str]] = {}
    for device, block in iter_device_blocks(case.show_outputs):
        m = _ALLOWED_VLANS.search(block)
        if m:
            evidence_line = m.group(0).splitlines()[-1].strip()
            per_device.setdefault(device, (_parse_vlan_list(m.group(1)), evidence_line))

    # R06 is inherently about the two ends of one trunk — no real case has more than two.
    if len(per_device) != 2:
        return []

    (d1, (vlans1, line1)), (d2, (vlans2, line2)) = per_device.items()
    restricted1 = len(vlans1) <= _UNRESTRICTED_VLAN_COUNT
    restricted2 = len(vlans2) <= _UNRESTRICTED_VLAN_COUNT

    if restricted1 and restricted2:
        findings = []
        for vlan in sorted(vlans1.symmetric_difference(vlans2)):
            side_with, evidence = (d1, line1) if vlan in vlans1 else (d2, line2)
            side_without = d2 if side_with == d1 else d1
            findings.append(
                Finding(
                    rule_id="R06_trunk_vlan_pruned",
                    severity="HIGH",
                    message=f"VLAN {vlan} is allowed on {side_with}'s trunk but not {side_without}'s",
                    evidence=evidence,
                )
            )
        return findings

    if restricted1 != restricted2:
        restricted_device, evidence = (d1, line1) if restricted1 else (d2, line2)
        other_device = d2 if restricted1 else d1
        return [
            Finding(
                rule_id="R06_trunk_vlan_pruned",
                severity="INFO",
                message=(
                    f"{restricted_device}'s trunk allows only a specific VLAN list while "
                    f"{other_device} carries the default unrestricted range — verify nothing needed is pruned"
                ),
                evidence=evidence,
            )
        ]

    # Both sides look "unrestricted" by the VLAN-count heuristic (e.g. two large, differently
    # curated lists that both happen to exceed _UNRESTRICTED_VLAN_COUNT) — without this, a real
    # mismatch here would be silently dropped instead of at least downgraded to advisory.
    if vlans1 != vlans2:
        return [
            Finding(
                rule_id="R06_trunk_vlan_pruned",
                severity="INFO",
                message=(
                    f"{d1} and {d2} both show large, unrestricted-looking VLAN lists that differ — "
                    "verify neither side is missing VLANs the other carries"
                ),
                evidence=line1,
            )
        ]
    return []


def _check_native_vlan_mismatch(case: Case) -> list[Finding]:
    m = _NATIVE_VLAN_MISMATCH_LOG.search(case.show_outputs)
    if not m:
        return []
    return [
        Finding(
            rule_id="R07_native_vlan_mismatch",
            severity="HIGH",
            message="CDP reports a native VLAN mismatch between the two trunk ends",
            evidence=m.group(0).strip(),
        )
    ]


_NONZERO_INPUT_ERRORS = re.compile(r"(?i)\b[1-9]\d*\s+input errors?\b")
_NONZERO_CRC = re.compile(r"(?i)\b[1-9]\d*\s+CRC\b")
_NONZERO_LATE_COLLISIONS = re.compile(r"(?i)\b[1-9]\d*\s+late collisions?\b")


def _check_duplex_mismatch(case: Case) -> list[Finding]:
    text = case.show_outputs
    # "show interfaces" always prints these counter labels, even at 0 — require an actual
    # nonzero count so a healthy interface's "0 input errors, 0 CRC" doesn't false-positive.
    has_errors = _NONZERO_INPUT_ERRORS.search(text) or _NONZERO_CRC.search(text)
    late_collisions = _NONZERO_LATE_COLLISIONS.search(text)
    if has_errors and late_collisions:
        return [
            Finding(
                rule_id="R13_duplex_mismatch",
                severity="HIGH",
                message="CRC/input errors on one side and late collisions on the other — classic duplex mismatch",
                evidence=find_line(text, late_collisions.group(0)),
            )
        ]
    return []
