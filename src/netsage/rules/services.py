"""R10 dhcp_relay_missing · R11 acl_zero_match · R12 nat_no_inside.

See docs/system_architecture.md §3 (C2).
"""

import re

from netsage.cases import Case
from netsage.rules.base import APIPA_PATTERN, Finding, find_line, iter_device_blocks

_ACL_ZERO_MATCH_LINE = re.compile(r"(?im)^\s*\d+\s+(?:permit|deny)\s+\S+.*\(0 matches\)")
_ACL_NUMBER = re.compile(r"(?i)access[- ]lists?\s+(\d+)")
_ACL_APPLIED = re.compile(r"(?im)(Inbound|Outgoing)\s+access list is (\d+)")
_NAT_OVERLOAD = re.compile(r"(?i)ip nat inside source.*overload")
# "Inside interfaces:" followed by a truly blank line — not just a header line with nothing
# after the colon, since interface names are listed on the *next* line, not appended to it.
_EMPTY_INSIDE_INTERFACES = re.compile(r"(?im)^Inside interfaces:\s*\n\s*\n")


def check(case: Case) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_check_dhcp_relay_missing(case))
    findings.extend(_check_acl_zero_match(case))
    findings.extend(_check_nat_no_inside(case))
    return findings


def _check_dhcp_relay_missing(case: Case) -> list[Finding]:
    text = case.show_outputs
    if not APIPA_PATTERN.search(text):
        return []
    # Router subinterface blocks that configure an address; some carry ip helper-address, some don't.
    subinterfaces = [b for _, b in iter_device_blocks(text) if re.search(r"(?i)ip address", b)]
    with_helper = [b for b in subinterfaces if "ip helper-address" in b]
    without_helper = [b for b in subinterfaces if "ip helper-address" not in b]
    if with_helper and without_helper:
        return [
            Finding(
                rule_id="R10_dhcp_relay_missing",
                severity="HIGH",
                message=(
                    "Some routed subinterfaces have 'ip helper-address' and at least one does not — "
                    "the DHCP client is likely on the one missing it"
                ),
                evidence=find_line(without_helper[0], "ip address"),
            )
        ]
    return []


def _check_acl_zero_match(case: Case) -> list[Finding]:
    text = case.show_outputs
    m = _ACL_ZERO_MATCH_LINE.search(text)
    if not m:
        return []

    findings = []
    acl_m = _ACL_NUMBER.search(text)
    acl_num = acl_m.group(1) if acl_m else "?"
    findings.append(
        Finding(
            rule_id="R11_acl_zero_match",
            severity="HIGH",
            message=f"ACL {acl_num} has a permit/deny line with 0 matches but is the stated intent",
            evidence=m.group(0).strip(),
        )
    )

    applied_m = _ACL_APPLIED.search(text)
    if applied_m:
        findings.append(
            Finding(
                rule_id="R11_acl_zero_match",
                severity="INFO",
                message=f"ACL {applied_m.group(2)} is applied {applied_m.group(1).lower()} — verify this is the intended direction/interface",
                evidence=find_line(text, applied_m.group(0)),
            )
        )
    return findings


def _check_nat_no_inside(case: Case) -> list[Finding]:
    text = case.show_outputs
    if _NAT_OVERLOAD.search(text) and _EMPTY_INSIDE_INTERFACES.search(text):
        return [
            Finding(
                rule_id="R12_nat_no_inside",
                severity="HIGH",
                message="NAT overload is configured but no inside interfaces are bound",
                evidence=find_line(text, "Inside interfaces"),
            )
        ]
    return []
