"""Case dataclass, CSV loader, and schema validation. See docs/case_dataset_specification.md."""

from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass

REQUIRED_FIELDS = [
    "case_id",
    "title",
    "category",
    "concept_tag",
    "symptom",
    "topology_note",
    "show_outputs",
    "expected_fault",
    "expected_root_cause",
    "osi_layer",
    "severity",
    "expected_next_command",
    "expected_fix_steps",
    "source_lab",
    "difficulty",
]

CASE_ID_PATTERN = re.compile(r"NS-\d{3}")

# Documented column order (dataset spec §4 / README) — the canonical order for coverage reports.
CATEGORIES = ["VLAN", "Gateway", "DHCP", "DNS", "Routing", "ACL", "NAT", "Wireless", "Switching", "Physical"]

# The 8 fault families the brief itself mandates (problem_statement.md). Switching/Physical were
# added on top and are not held to the same "at least 3 cases" floor (dataset spec §6 rule 6).
BRIEF_MANDATED_CATEGORIES = ["VLAN", "Gateway", "DHCP", "DNS", "Routing", "ACL", "NAT", "Wireless"]

OSI_LAYERS = ["L1", "L1/L2", "L2", "L2/L3", "L3", "L3/L4", "L4", "L4/L7", "L7"]
SEVERITIES = ["Critical", "High", "Medium", "Low"]
DIFFICULTIES = ["Easy", "Medium", "Hard"]

# The 36 fault-mechanism tags (dataset spec §3) plus the one reserved abstain tag the model may
# return, which is also a legitimate ground-truth answer for a healthy control case.
ROOT_CAUSE_TAGS = {
    "vlan_wrong_access_assignment",
    "vlan_not_defined",
    "vlan_pruned_from_trunk",
    "native_vlan_mismatch",
    "host_wrong_default_gateway",
    "interface_shutdown",
    "duplicate_ip_address",
    "wrong_subnet_mask",
    "dhcp_relay_missing",
    "dhcp_pool_exhausted",
    "dhcp_wrong_default_router",
    "rogue_dhcp_server",
    "dns_client_not_configured",
    "acl_blocks_dns",
    "dns_record_missing",
    "router_name_server_missing",
    "missing_return_route",
    "ospf_area_mismatch",
    "ospf_wrong_wildcard",
    "default_route_missing",
    "acl_wrong_direction",
    "acl_blocks_return_traffic",
    "acl_rule_order",
    "acl_wrong_interface",
    "nat_missing_inside_interface",
    "nat_acl_missing_subnet",
    "nat_pool_exhausted",
    "static_nat_wrong_inside_local",
    "guest_isolation_missing",
    "wireless_psk_mismatch",
    "ap_uplink_not_trunk",
    "dhcp_scope_missing",
    "port_security_violation",
    "duplex_mismatch",
    "missing_clock_rate",
    "stp_wrong_root_bridge",
    "insufficient_evidence",
}

# A device/host prompt line: "R1# show ip route", "SW1# show vlan brief", "PC1> ping ...".
# Shared with rules/base.py's iter_device_blocks (which needs the capture groups to split
# blocks) — one definition, so validate_cases and the rule engine agree on what counts as a
# prompt line instead of drifting apart.
PROMPT_LINE_PATTERN = re.compile(r"(?m)^(\S+)[#>]\s*(.*)$")

_MIN_SHOW_OUTPUTS_LENGTH = 80


class SchemaError(Exception):
    """The CSV header doesn't match the documented 15-column contract (missing/extra/reordered)."""


@dataclass(frozen=True)
class Case:
    case_id: str
    title: str
    category: str
    concept_tag: str
    symptom: str
    topology_note: str
    show_outputs: str
    expected_fault: str
    expected_root_cause: str
    osi_layer: str
    severity: str
    expected_next_command: str
    expected_fix_steps: str
    source_lab: str
    difficulty: str

    def to_prompt_context(self) -> dict:
        """Symptom, topology note and show output only — what the model is allowed to see. [DR-06]"""
        return {
            "case_id": self.case_id,
            "symptom": self.symptom,
            "topology_note": self.topology_note,
            "show_outputs": self.show_outputs,
        }

    def ground_truth(self) -> dict:
        """The answer key. Never pass this into prompt construction. [DR-06]"""
        return {
            "expected_fault": self.expected_fault,
            "expected_root_cause": self.expected_root_cause,
            "osi_layer": self.osi_layer,
            "expected_next_command": self.expected_next_command,
            "expected_fix_steps": self.expected_fix_steps,
        }


def load_cases(path: str) -> list[Case]:
    """Loads cases.csv with a real CSV parser — never split show_outputs on commas. [FR-01]

    Raises SchemaError if the header doesn't match REQUIRED_FIELDS exactly, in order.
    Raises FileNotFoundError if path doesn't exist (left uncaught — the CLI maps it to exit 2).
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != REQUIRED_FIELDS:
            raise SchemaError(
                f"expected columns {REQUIRED_FIELDS!r} in that exact order, got {list(reader.fieldnames or [])!r}"
            )
        return [Case(**{field: row[field] for field in REQUIRED_FIELDS}) for row in reader]


@dataclass
class ValidationReport:
    valid: bool
    case_count: int
    category_counts: dict[str, int]
    severity_counts: dict[str, int]
    errors: list[str]
    warnings: list[str]


def validate_cases(cases: list[Case]) -> ValidationReport:
    """[auto] checks from docs/case_dataset_specification.md §6, rules 1-6.

    Rules 7-12 in that section (one fault per case, no diagnostic vocabulary in the symptom,
    a healthy control line present, fix verified in the simulator, next_command real, no
    duplicate root-cause tag) are peer-review only and are not checked here.
    """
    errors: list[str] = []
    warnings: list[str] = []
    id_counts: Counter[str] = Counter()

    for case in cases:
        id_counts[case.case_id] += 1

        # rule 1: case_id matches NS-\d{3}
        if not CASE_ID_PATTERN.fullmatch(case.case_id):
            errors.append(f"{case.case_id!r}: case_id does not match NS-\\d{{3}}")

        # rule 2: no required field blank — a short CSV row makes csv.DictReader fill missing
        # trailing columns with None, so treat that the same as an empty string rather than
        # crashing on .strip()
        for field_name in REQUIRED_FIELDS:
            if not (getattr(case, field_name) or "").strip():
                errors.append(f"{case.case_id}: required field {field_name!r} is blank")

        # rule 3: enum fields within vocabulary
        if case.category not in CATEGORIES:
            errors.append(f"{case.case_id}: unknown category {case.category!r}")
        if case.osi_layer not in OSI_LAYERS:
            errors.append(f"{case.case_id}: unknown osi_layer {case.osi_layer!r}")
        if case.severity not in SEVERITIES:
            errors.append(f"{case.case_id}: unknown severity {case.severity!r}")
        if case.difficulty not in DIFFICULTIES:
            errors.append(f"{case.case_id}: unknown difficulty {case.difficulty!r}")

        # rule 4: expected_root_cause in the tag list
        if case.expected_root_cause not in ROOT_CAUSE_TAGS:
            errors.append(f"{case.case_id}: unknown expected_root_cause {case.expected_root_cause!r}")

        # rule 5: show_outputs long enough and contains a device/host prompt line
        if len(case.show_outputs) < _MIN_SHOW_OUTPUTS_LENGTH:
            errors.append(f"{case.case_id}: show_outputs is shorter than {_MIN_SHOW_OUTPUTS_LENGTH} characters")
        if not PROMPT_LINE_PATTERN.search(case.show_outputs):
            errors.append(f"{case.case_id}: show_outputs has no '<DEVICE># <command>' or '<HOST>> <command>' prompt line")

    for case_id, count in id_counts.items():
        if count > 1:
            errors.append(f"{case_id!r}: duplicate case_id ({count} rows)")

    category_counts = dict(Counter(c.category for c in cases))
    severity_counts = dict(Counter(c.severity for c in cases))

    # rule 6: warn (don't fail) when a brief-mandated family has fewer than 3 cases
    for family in BRIEF_MANDATED_CATEGORIES:
        count = category_counts.get(family, 0)
        if count < 3:
            warnings.append(f"category {family!r} has fewer than 3 cases ({count})")

    return ValidationReport(
        valid=not errors,
        case_count=len(cases),
        category_counts=category_counts,
        severity_counts=severity_counts,
        errors=errors,
        warnings=warnings,
    )
