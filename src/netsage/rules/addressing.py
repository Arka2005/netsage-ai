"""R01 duplicate_ip · R02 mask_mismatch · R03 gateway_mismatch · R09 apipa_address.

See docs/system_architecture.md §3 (C2).
"""

import ipaddress
import re

from netsage.cases import Case
from netsage.rules.base import Finding, find_line, iter_device_blocks

# Packet Tracer's ipconfig-style output: "IPv4 Address: 10.10.20.55" / "IP Address: ...".
_ADDRESS_LABEL = re.compile(r"(?im)IP(?:v4)?\s*Address:\s*(\d{1,3}(?:\.\d{1,3}){3})")
# "show ip interface brief" table rows: "GigabitEthernet0/0.10  10.10.10.1  YES manual up  up".
_INTERFACE_BRIEF_ROW = re.compile(
    r"(?im)^(\S*(?:Ethernet|Serial|Vlan|Loopback|Port-channel)\S*)\s+(\d{1,3}(?:\.\d{1,3}){3})\s+YES"
)
_MASK_LABEL = re.compile(r"(?im)Subnet Mask:\s*(\d{1,3}(?:\.\d{1,3}){3})")
_GATEWAY_LABEL = re.compile(r"(?im)Default Gateway:\s*(\d{1,3}(?:\.\d{1,3}){3})")
_APIPA = re.compile(r"\b169\.254\.\d{1,3}\.\d{1,3}\b")
_INTERFACE_HINT = re.compile(r"(?i)(GigabitEthernet|FastEthernet|Serial|Vlan|Loopback|Port-channel)\S*")

# "0.0.0.0" is Packet Tracer's sentinel for "no gateway configured" (e.g. after failed DHCP) —
# not a real misconfigured value, so mask/gateway rules ignore it to avoid a redundant finding on
# top of R09_apipa_address, which already flags the underlying DHCP failure.
_UNSET_GATEWAY = "0.0.0.0"


def check(case: Case) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_check_duplicate_ip(case))
    findings.extend(_check_mask_mismatch(case))
    findings.extend(_check_gateway_mismatch(case))
    findings.extend(_check_apipa_address(case))
    return findings


def _check_duplicate_ip(case: Case) -> list[Finding]:
    seen: dict[str, str] = {}
    findings = []
    for device, block in iter_device_blocks(case.show_outputs):
        owned_addresses = [(addr, device) for addr in _ADDRESS_LABEL.findall(block)]
        owned_addresses += [(addr, iface) for iface, addr in _INTERFACE_BRIEF_ROW.findall(block)]
        for addr, owner in owned_addresses:
            existing_owner = seen.setdefault(addr, owner)
            if existing_owner != owner:
                findings.append(
                    Finding(
                        rule_id="R01_duplicate_ip",
                        severity="HIGH",
                        message=f"{addr} is configured as the address on both {existing_owner} and {owner}",
                        evidence=find_line(block, addr),
                    )
                )
    return findings


def _check_mask_mismatch(case: Case) -> list[Finding]:
    findings = []
    for device, block in iter_device_blocks(case.show_outputs):
        ip_m = _ADDRESS_LABEL.search(block)
        mask_m = _MASK_LABEL.search(block)
        gw_m = _GATEWAY_LABEL.search(block)
        if not (ip_m and mask_m and gw_m):
            continue
        ip, mask, gw = ip_m.group(1), mask_m.group(1), gw_m.group(1)
        if gw == _UNSET_GATEWAY:
            continue
        try:
            network = ipaddress.ip_network(f"{ip}/{mask}", strict=False)
            if ipaddress.ip_address(gw) not in network:
                findings.append(
                    Finding(
                        rule_id="R02_mask_mismatch",
                        severity="HIGH",
                        message=f"{device}'s subnet mask {mask} puts its own gateway {gw} outside {network}",
                        evidence=find_line(block, mask),
                    )
                )
        except ValueError:
            continue
    return findings


def _check_gateway_mismatch(case: Case) -> list[Finding]:
    findings = []
    text = case.show_outputs
    blocks = iter_device_blocks(text)
    for m in _GATEWAY_LABEL.finditer(text):
        gw = m.group(1)
        if gw == _UNSET_GATEWAY:
            continue
        # The gateway must be bound to a real router/SVI interface somewhere in the evidence — a
        # bare text search would also match the gateway showing up in a diagnostic ping/tracert
        # line, so require it to co-occur with an interface-name token within the same block.
        bound_to_interface = any(gw in block and _INTERFACE_HINT.search(block) for _device, block in blocks)
        if not bound_to_interface:
            findings.append(
                Finding(
                    rule_id="R03_gateway_mismatch",
                    severity="HIGH",
                    message=f"Configured gateway {gw} does not appear bound to any router or SVI interface in the evidence",
                    evidence=find_line(text, gw),
                )
            )
    return findings


def _check_apipa_address(case: Case) -> list[Finding]:
    m = _APIPA.search(case.show_outputs)
    if not m:
        return []
    return [
        Finding(
            rule_id="R09_apipa_address",
            severity="HIGH",
            message=f"Host has an APIPA address {m.group(0)} — DHCP did not complete",
            evidence=find_line(case.show_outputs, m.group(0)),
        )
    ]
