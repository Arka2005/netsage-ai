"""One firing + one non-firing fixture per rule (R01-R14), per docs/project_requirements.md NFR-06.

Text is shaped like the real dataset's show_outputs, calibrated against data/cases.csv rather
than guessed Cisco formatting.
"""

from netsage.cases import Case
from netsage.rules import check


def _case(show_outputs: str) -> Case:
    return Case(
        case_id="NS-000",
        title="t",
        category="VLAN",
        concept_tag="c",
        symptom="s",
        topology_note="t",
        show_outputs=show_outputs,
        expected_fault="f",
        expected_root_cause="vlan_not_defined",
        osi_layer="L2",
        severity="High",
        expected_next_command="show x",
        expected_fix_steps="fix",
        source_lab="lab.pkt",
        difficulty="Easy",
    )


def _rule_ids(case: Case) -> set[str]:
    return {f.rule_id for f in check(case)}


def test_r01_duplicate_ip_fires_on_shared_address():
    text = (
        "PRINTER> ipconfig\nIPv4 Address: 10.10.10.1\nSubnet Mask: 255.255.255.0\n\n"
        "R1# show ip interface brief | include Gi0/0.10\n"
        "GigabitEthernet0/0.10  10.10.10.1  YES manual up  up\n"
    )
    assert "R01_duplicate_ip" in _rule_ids(_case(text))


def test_r01_duplicate_ip_does_not_fire_on_distinct_addresses():
    text = (
        "PRINTER> ipconfig\nIPv4 Address: 10.10.10.5\nSubnet Mask: 255.255.255.0\n\n"
        "R1# show ip interface brief | include Gi0/0.10\n"
        "GigabitEthernet0/0.10  10.10.10.1  YES manual up  up\n"
    )
    assert "R01_duplicate_ip" not in _rule_ids(_case(text))


def test_r02_mask_mismatch_fires_when_gateway_outside_subnet():
    text = "PC1> ipconfig /all\nIPv4 Address: 10.10.10.5\nSubnet Mask: 255.255.255.0\nDefault Gateway: 10.10.20.1\n"
    assert "R02_mask_mismatch" in _rule_ids(_case(text))


def test_r02_mask_mismatch_does_not_fire_when_gateway_inside_subnet():
    text = "PC1> ipconfig /all\nIPv4 Address: 10.10.10.5\nSubnet Mask: 255.255.255.0\nDefault Gateway: 10.10.10.1\n"
    assert "R02_mask_mismatch" not in _rule_ids(_case(text))


def test_r03_gateway_mismatch_fires_when_gateway_unbound():
    text = (
        "PC5> ipconfig /all\nIPv4 Address: 10.10.20.55\nSubnet Mask: 255.255.255.0\nDefault Gateway: 10.10.20.254\n\n"
        "PC5> ping 10.10.20.254\nRequest timed out.\n\n"
        "R1# show ip interface brief | include Gi0/0\nGigabitEthernet0/0.20  10.10.20.1   YES manual up  up\n"
    )
    assert "R03_gateway_mismatch" in _rule_ids(_case(text))


def test_r03_gateway_mismatch_does_not_fire_when_gateway_is_bound():
    text = (
        "PC5> ipconfig /all\nIPv4 Address: 10.10.20.55\nSubnet Mask: 255.255.255.0\nDefault Gateway: 10.10.20.1\n\n"
        "R1# show ip interface brief | include Gi0/0\nGigabitEthernet0/0.20  10.10.20.1   YES manual up  up\n"
    )
    assert "R03_gateway_mismatch" not in _rule_ids(_case(text))


def test_r04_interface_down_fires_on_administratively_down():
    text = "R1# show interfaces Gi0/1\nGigabitEthernet0/1 is administratively down, line protocol is down\n"
    assert "R04_interface_down" in _rule_ids(_case(text))


def test_r04_interface_down_does_not_fire_on_up_up():
    text = "R1# show interfaces Gi0/1\nGigabitEthernet0/1 is up, line protocol is up\n" + "x" * 40
    assert "R04_interface_down" not in _rule_ids(_case(text))


def test_r05_vlan_missing_fires_on_inactive_vlan():
    text = "SW2# show interfaces Fa0/10 switchport\nAccess Mode VLAN: 30 (Inactive)\n"
    assert "R05_vlan_missing" in _rule_ids(_case(text))


def test_r05_vlan_missing_does_not_fire_on_active_vlan():
    text = "SW1# show interfaces Fa0/3 switchport\nAccess Mode VLAN: 20 (ENG)\n" + "x" * 40
    assert "R05_vlan_missing" not in _rule_ids(_case(text))


def test_r06_trunk_vlan_pruned_fires_on_restricted_vs_unrestricted():
    text = (
        "SW1# show interfaces trunk\nPort      Vlans allowed on trunk\nGi0/1     20,30\n\n"
        "SW2# show interfaces trunk\nPort      Vlans allowed on trunk\nGi0/1     1-4094\n"
    )
    assert "R06_trunk_vlan_pruned" in _rule_ids(_case(text))


def test_r06_trunk_vlan_pruned_does_not_fire_on_matching_lists():
    text = (
        "SW1# show interfaces trunk\nPort      Vlans allowed on trunk\nGi0/1     20,30\n\n"
        "SW2# show interfaces trunk\nPort      Vlans allowed on trunk\nGi0/1     20,30\n"
    )
    assert "R06_trunk_vlan_pruned" not in _rule_ids(_case(text))


def test_r07_native_vlan_mismatch_fires_on_cdp_log():
    text = (
        "SW1# show logging | include NATIVE\n"
        "%CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch discovered on GigabitEthernet0/1 (99), "
        "with SW3 GigabitEthernet0/2 (1).\n"
    )
    assert "R07_native_vlan_mismatch" in _rule_ids(_case(text))


def test_r07_native_vlan_mismatch_does_not_fire_without_cdp_log():
    text = (
        "SW1# show interfaces trunk\nPort      Mode  Encapsulation  Status    Native vlan\n"
        "Gi0/1     on    802.1q         trunking  1\n"
    )
    assert "R07_native_vlan_mismatch" not in _rule_ids(_case(text))


def test_r08_route_missing_fires_when_no_gateway_and_unreachable():
    text = (
        "R2# show ip route | begin Gateway\nGateway of last resort is not set\n\n"
        "PC1> tracert 172.16.50.10\n 1  10.10.10.1\n 2  *  *  *  Request timed out.\n"
    )
    assert "R08_route_missing" in _rule_ids(_case(text))


def test_r08_route_missing_does_not_fire_when_gateway_is_set():
    text = (
        "R2# show ip route | begin Gateway\nGateway of last resort is 192.168.100.1 to network 0.0.0.0\n\n"
        "PC1> tracert 172.16.50.10\n 1  10.10.10.1\n 2  172.16.50.10\n"
    )
    assert "R08_route_missing" not in _rule_ids(_case(text))


def test_r09_apipa_address_fires_on_169_254():
    text = "PC1> ipconfig\nIPv4 Address: 169.254.71.4\nSubnet Mask: 255.255.0.0\nDefault Gateway: 0.0.0.0\n"
    assert "R09_apipa_address" in _rule_ids(_case(text))


def test_r09_apipa_address_does_not_fire_on_real_dhcp_address():
    text = "PC1> ipconfig\nIPv4 Address: 10.10.20.55\nSubnet Mask: 255.255.255.0\nDefault Gateway: 10.10.20.1\n"
    assert "R09_apipa_address" not in _rule_ids(_case(text))


def test_r10_dhcp_relay_missing_fires_on_inconsistent_helper():
    text = (
        "R1# show running-config interface Gi0/0.30\ninterface GigabitEthernet0/0.30\n"
        " ip address 10.10.30.1 255.255.255.0\n\n"
        "R1# show running-config interface Gi0/0.20\ninterface GigabitEthernet0/0.20\n"
        " ip address 10.10.20.1 255.255.255.0\n ip helper-address 10.10.99.10\n\n"
        "PC9> ipconfig\nIPv4 Address: 169.254.12.9\n"
    )
    assert "R10_dhcp_relay_missing" in _rule_ids(_case(text))


def test_r10_dhcp_relay_missing_does_not_fire_when_dhcp_succeeds():
    text = (
        "R1# show running-config interface Gi0/0.30\ninterface GigabitEthernet0/0.30\n"
        " ip address 10.10.30.1 255.255.255.0\n\n"
        "PC9> ipconfig\nIPv4 Address: 10.10.30.55\n"
    )
    assert "R10_dhcp_relay_missing" not in _rule_ids(_case(text))


def test_r11_acl_zero_match_fires_on_zero_match_line():
    text = (
        "R1# show access-lists 110\nExtended IP access list 110\n"
        " 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)\n\n"
        "R1# show ip interface Gi0/0.99 | include access list\n  Inbound  access list is 110\n"
    )
    assert "R11_acl_zero_match" in _rule_ids(_case(text))


def test_r11_acl_zero_match_does_not_fire_when_all_lines_match():
    text = (
        "R1# show access-lists 110\nExtended IP access list 110\n"
        " 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (5 matches)\n"
        " 20 permit ip any any (12 matches)\n"
    )
    assert "R11_acl_zero_match" not in _rule_ids(_case(text))


def test_r12_nat_no_inside_fires_when_inside_interfaces_empty():
    text = (
        "R1# show ip nat statistics\nOutside interfaces:\n  GigabitEthernet0/1\nInside interfaces:\n\n"
        "R1# show running-config | include ip nat\n"
        "ip nat inside source list 1 interface GigabitEthernet0/1 overload\n"
    )
    assert "R12_nat_no_inside" in _rule_ids(_case(text))


def test_r12_nat_no_inside_does_not_fire_when_inside_interfaces_populated():
    text = (
        "R1# show ip nat statistics\nOutside interfaces:\n  GigabitEthernet0/1\n"
        "Inside interfaces:\n  GigabitEthernet0/0.10\n\n"
        "R1# show running-config | include ip nat\n"
        "ip nat inside source list 1 interface GigabitEthernet0/1 overload\n"
    )
    assert "R12_nat_no_inside" not in _rule_ids(_case(text))


def test_r13_duplex_mismatch_fires_on_nonzero_errors_and_collisions():
    text = "SW1# show interfaces Fa0/5\n  5 input errors, 0 CRC\n  3 late collisions\n"
    assert "R13_duplex_mismatch" in _rule_ids(_case(text))


def test_r13_duplex_mismatch_does_not_fire_on_healthy_zeroed_counters():
    text = (
        "SW1# show interfaces Fa0/5\n"
        "  0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored\n"
        "  0 late collisions, 0 deferred\n"
    )
    assert "R13_duplex_mismatch" not in _rule_ids(_case(text))


def test_r14_ospf_area_mismatch_fires_on_different_areas():
    text = (
        "R1# show running-config | section router ospf\nrouter ospf 1\n network 10.10.10.0 0.0.0.255 area 0\n\n"
        "R3# show running-config | section router ospf\nrouter ospf 1\n network 172.16.60.0 0.0.0.255 area 1\n"
    )
    assert "R14_ospf_area_mismatch" in _rule_ids(_case(text))


def test_r14_ospf_area_mismatch_does_not_fire_on_matching_areas():
    text = (
        "R1# show running-config | section router ospf\nrouter ospf 1\n network 10.10.10.0 0.0.0.255 area 0\n\n"
        "R3# show running-config | section router ospf\nrouter ospf 1\n network 172.16.60.0 0.0.0.255 area 0\n"
    )
    assert "R14_ospf_area_mismatch" not in _rule_ids(_case(text))


def test_no_rules_fire_on_a_boring_healthy_case():
    text = "PC2> ping 10.10.99.20\nReply from 10.10.99.20: bytes=32 time=1ms TTL=128\n" + "x" * 40
    assert _rule_ids(_case(text)) == set()
