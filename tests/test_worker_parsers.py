from cyberWatch.workers.worker import _parse_scamper_hops, _parse_traceroute_hops


def test_parse_traceroute_hops_with_average_rtt():
    output = """
traceroute to 8.8.8.8 (8.8.8.8), 30 hops max
 1  192.168.1.1  0.456 ms  0.412 ms  0.398 ms
 2  10.0.0.1  5.100 ms  5.300 ms  5.500 ms
"""

    hops = _parse_traceroute_hops(output)

    assert len(hops) == 2
    assert hops[0].hop == 1
    assert hops[0].ip == "192.168.1.1"
    assert hops[0].rtt_ms == (0.456 + 0.412 + 0.398) / 3
    assert hops[1].hop == 2
    assert hops[1].ip == "10.0.0.1"
    assert hops[1].rtt_ms == (5.100 + 5.300 + 5.500) / 3


def test_parse_traceroute_timeout_hop():
    output = """
traceroute to 8.8.8.8 (8.8.8.8), 30 hops max
 1  192.168.1.1  0.456 ms
 2  * * *
"""

    hops = _parse_traceroute_hops(output)

    assert len(hops) == 2
    assert hops[1].hop == 2
    assert hops[1].ip is None
    assert hops[1].rtt_ms is None


def test_parse_scamper_hops():
    output = """
trace to 8.8.8.8
 1  192.168.1.1  0.456 ms
 2  10.0.0.1  5.123 ms
"""

    hops = _parse_scamper_hops(output)

    assert len(hops) == 2
    assert hops[0].hop == 1
    assert hops[0].ip == "192.168.1.1"
    assert hops[0].rtt_ms == 0.456
    assert hops[1].hop == 2
    assert hops[1].ip == "10.0.0.1"
    assert hops[1].rtt_ms == 5.123
