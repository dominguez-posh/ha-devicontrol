"""Protocol tests with images captured from a real device (firmware 2.12)."""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[1] / "custom_components" / "kermi_ecotimer" / "protocol.py"
_spec = importlib.util.spec_from_file_location("protocol", _path)
proto = importlib.util.module_from_spec(_spec)
sys.modules["protocol"] = proto
_spec.loader.exec_module(proto)

ALL_COMFORT = b"\xff" * 168


def image(header_hex: str, program: bytes = ALL_COMFORT) -> bytes:
    return bytes.fromhex(header_hex) + program


# dial on 3, boost running, all comfort
BOOST_DIAL3 = image("01 0b 60 fa 38 00 98 3b 00 1e b8 6c fe 03 00 00 40 10 00 00")
# dial on snowflake, boost running
BOOST_FROST = image("01 04 60 ea 00 00 98 2e 00 1e b9 2c fe 03 00 00 40 10 00 00")
# dial on 5
DIAL5 = image("01 10 e0 f7 64 00 98 11 00 1e 78 61 fe 03 00 00 40 10 00 00")
# all antifreeze written, boost running
ANTIFREEZE = image("01 0b 60 f9 38 00 98 0e 04 1e 0d 67 fe 03 00 00 40 10 00 00", b"\x00" * 168)


def test_parse_dial3_boost():
    s = proto.parse(BOOST_DIAL3)
    assert s.setpoint == 18.2
    assert s.actual == 25.0
    assert s.dial_percent == 56
    assert s.relay and s.boost and s.dst_europe
    assert not s.window_open and not s.temperature_limit
    assert s.boost_remaining == 59
    assert s.eco_offset == 3.0
    assert s.eco_temperature == 15.2
    assert s.active_phase == 0
    assert s.uniform_mode() == proto.MODE_COMFORT


def test_parse_dial_extremes():
    assert proto.parse(BOOST_FROST).setpoint == 7.0
    assert proto.parse(BOOST_FROST).actual == 23.4
    assert proto.parse(DIAL5).setpoint == 27.0
    assert proto.parse(DIAL5).dial_percent == 100


def test_antifreeze_phase():
    s = proto.parse(ANTIFREEZE)
    assert s.active_phase == 4
    assert s.uniform_mode() == proto.MODE_ANTIFREEZE
    assert s.temperature_for_mode(s.mode_at(datetime(2026, 10, 25, 12))) == 7.0


def test_eco_phase():
    s = proto.parse(image("01 0b 60 ee 38 00 08 00 03 1e ec 9b fe 03 00 00 40 10 00 00", b"\x55" * 168))
    assert proto.ACTIVE_PHASES[s.active_phase] == "eco"
    assert s.uniform_mode() == proto.MODE_ECO
    assert not s.relay and not s.boost


def test_program_roundtrip():
    program = proto.uniform_program(proto.MODE_ECO)
    program[0][24:34] = [proto.MODE_COMFORT] * 10  # Monday 06:00-08:30
    program[6][95] = proto.MODE_ANTIFREEZE  # Sunday 23:45
    assert proto.decode_program(proto.encode_program(program)) == program
    assert proto.day_summary(program[0]) == [
        ("00:00", "06:00", "eco"), ("06:00", "08:30", "comfort"), ("08:30", "24:00", "eco")]


def test_build_image_like_app():
    s = proto.parse(BOOST_DIAL3)
    # boost off: only bit4 changes, the app clears every other bit of byte 6
    off = proto.build_image(s, boost=False)
    assert off[6] == 0x00
    assert off[:6] == BOOST_DIAL3[:6] and off[7:] == BOOST_DIAL3[7:]
    on = proto.build_image(proto.parse(off), boost=True, eco_offset=2.5)
    assert on[6] == 0x10 and on[9] == 25
    frost = proto.build_image(s, program=proto.uniform_program(0))
    assert frost[20:] == b"\x00" * 168


def test_eco_offset_is_clamped():
    s = proto.parse(BOOST_DIAL3)
    assert proto.build_image(s, eco_offset=50)[9] == 200
    assert proto.build_image(s, eco_offset=0)[9] == 20


def test_fragments_match_app():
    frags = proto.fragments(BOOST_DIAL3)
    assert frags[0][:2] == b"\x00\x00" and len(frags[0]) == 22
    assert frags[1][:2] == b"\x14\x00" and len(frags[1]) == 170
    assert frags[0][2:] + frags[1][2:] == BOOST_DIAL3


def test_time_roundtrip():
    dt = datetime(2026, 10, 25, 9, 45, 40)
    payload = proto.encode_time(dt)
    assert payload.hex(" ") == "ea 07 0a 19 09 2d 28 07 00 00"
    assert proto.decode_time(payload) == dt
    # value read from a device that was never set
    assert proto.decode_time(bytes.fromhex("e5 07 05 06 05 1f 11 04 00 00")) == datetime(2021, 5, 6, 5, 31, 17)


def test_device_name_is_cut_to_15_bytes():
    assert proto.device_name_bytes("Bad Klein") == b"Bad Klein"
    assert proto.device_name_bytes("Bad Klein Handtuch Trockner") == b"Bad Klein Handt"
    # never split the two-byte 'ß'
    assert proto.device_name_bytes("Bad Großßßßßßßß") == "Bad Großßßß".encode()
    assert len(proto.device_name_bytes("Bad Großßßßßßßß")) <= 15


@pytest.mark.parametrize(("text", "slot"), [("00:00", 0), ("06:30", 26), ("06:44", 26), ("24:00", 96)])
def test_parse_slot(text, slot):
    assert proto.parse_slot(text) == slot


@pytest.mark.parametrize("text", ["25:00", "24:15", "7", "12:60"])
def test_parse_slot_invalid(text):
    with pytest.raises(ValueError):
        proto.parse_slot(text)
