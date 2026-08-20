"""R08 route_missing · R14 ospf_area_mismatch.

See docs/system_architecture.md §3 (C2).
"""

import re

from netsage.cases import Case
from netsage.rules.base import Finding, find_line, iter_device_blocks

_NO_GATEWAY_OF_LAST_RESORT = "Gateway of last resort is not set"
_REACHABILITY_FAILURE = re.compile(r"(?i)Request timed out|Destination host unreachable")
_OSPF_AREA = re.compile(r"(?im)\barea\s+(\d+)\b")


def check(case: Case) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_check_route_missing(case))
    findings.extend(_check_ospf_area_mismatch(case))
    return findings


def _check_route_missing(case: Case) -> list[Finding]:
    text = case.show_outputs
    if _NO_GATEWAY_OF_LAST_RESORT in text and _REACHABILITY_FAILURE.search(text):
        return [
            Finding(
                rule_id="R08_route_missing",
                severity="HIGH",
                message="No gateway of last resort and a reachability test failed — a route is likely missing",
                evidence=find_line(text, _NO_GATEWAY_OF_LAST_RESORT),
            )
        ]
    return []


def _check_ospf_area_mismatch(case: Case) -> list[Finding]:
    per_device: dict[str, tuple[str, str]] = {}
    for device, block in iter_device_blocks(case.show_outputs):
        m = _OSPF_AREA.search(block)
        if m:
            per_device.setdefault(device, (m.group(1), find_line(block, m.group(0))))

    devices = list(per_device)
    findings = []
    for i in range(len(devices)):
        for j in range(i + 1, len(devices)):
            d1, d2 = devices[i], devices[j]
            area1, line1 = per_device[d1]
            area2, _line2 = per_device[d2]
            if area1 != area2:
                findings.append(
                    Finding(
                        rule_id="R14_ospf_area_mismatch",
                        severity="HIGH",
                        message=f"OSPF area mismatch: {d1} area {area1}, {d2} area {area2}",
                        evidence=line1,
                    )
                )
    return findings
