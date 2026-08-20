"""Shared pytest fixtures for the netsage test suite."""

import csv
import pathlib

import pytest

CASE_COLUMNS = [
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

_ROWS = [
    {
        "case_id": "NS-001",
        "title": "Access port in wrong VLAN",
        "category": "VLAN",
        "concept_tag": "vlan-assignment",
        "symptom": "PC1 in the Sales area gets 169.254.x.x instead of a 10.10.10.0/24 address.",
        "topology_note": "SW1 Fa0/3 is patched to PC1. Sales = VLAN 10 (10.10.10.0/24).",
        "show_outputs": "SW1# show vlan brief\nVLAN Name      Status    Ports\n10   SALES     active    Fa0/1, Fa0/2",
        "expected_fault": "Fa0/3 is assigned to the wrong access VLAN.",
        "expected_root_cause": "vlan_wrong_access_assignment",
        "osi_layer": "L2",
        "severity": "High",
        "expected_next_command": "show interfaces Fa0/3 switchport",
        "expected_fix_steps": "Set Fa0/3 access vlan to 10; re-test DHCP.",
        "source_lab": "lab-vlan-basics.pkt",
        "difficulty": "Easy",
    },
    {
        "case_id": "NS-002",
        "title": "Healthy control case, no fault",
        "category": "VLAN",
        "concept_tag": "abstain-control",
        "symptom": "PC2 in Engineering can reach the file server without issue.",
        "topology_note": "SW1 Fa0/4 is patched to PC2. Engineering = VLAN 20 (10.10.20.0/24).",
        "show_outputs": "SW1# show vlan brief\nVLAN Name      Status    Ports\n20   ENG       active    Fa0/4\nPC2> ping 10.10.99.20\nReply from 10.10.99.20: bytes=32 time=1ms TTL=128",
        "expected_fault": "None — this is a healthy control case.",
        "expected_root_cause": "insufficient_evidence",
        "osi_layer": "L2",
        "severity": "Low",
        "expected_next_command": "show interfaces Fa0/4 switchport",
        "expected_fix_steps": "No fix required.",
        "source_lab": "lab-vlan-basics.pkt",
        "difficulty": "Easy",
    },
]


@pytest.fixture
def make_case_row():
    """Factory: a valid case row with one or more fields overridden, to test one violation at a time."""

    def _make(**overrides) -> dict:
        row = dict(_ROWS[0])
        row.update(overrides)
        return row

    return _make


@pytest.fixture
def write_cases_csv():
    """Factory: writes rows to path as an RFC 4180 CSV (LF endings, every field quoted); returns the path."""

    def _write(path: pathlib.Path, rows: list[dict], header: list[str] | None = None) -> str:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
            f, fieldnames=header or CASE_COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\n", extrasaction="ignore"
        )
            writer.writeheader()
            writer.writerows(rows)
        return str(path)

    return _write


@pytest.fixture
def tmp_cases_csv(tmp_path: pathlib.Path, write_cases_csv) -> str:
    """Writes a minimal 2-row cases.csv (all 15 columns) and returns its path."""
    return write_cases_csv(tmp_path / "cases_mini.csv", _ROWS)
