"""Deterministic rule registry — pure functions check(case) -> list[Finding]. See docs/system_architecture.md §3 (C2)."""

from netsage.cases import Case
from netsage.rules import addressing, layer2, layer3, services
from netsage.rules.base import Finding

_MODULES = [addressing, layer2, layer3, services]

ALL_RULE_IDS = [
    "R01_duplicate_ip",
    "R02_mask_mismatch",
    "R03_gateway_mismatch",
    "R04_interface_down",
    "R05_vlan_missing",
    "R06_trunk_vlan_pruned",
    "R07_native_vlan_mismatch",
    "R08_route_missing",
    "R09_apipa_address",
    "R10_dhcp_relay_missing",
    "R11_acl_zero_match",
    "R12_nat_no_inside",
    "R13_duplex_mismatch",
    "R14_ospf_area_mismatch",
]


def check(case: Case) -> list[Finding]:
    findings: list[Finding] = []
    for module in _MODULES:
        findings.extend(module.check(case))
    return findings
