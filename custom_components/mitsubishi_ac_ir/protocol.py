"""Mitsubishi AC IR encoder: AcState -> 18-byte packet -> timings -> Zigbee2MQTT code.

Standard library only. This is a trimmed copy of the research code at the
repo root (mitsu_ir.py, ir_decode.py); see KNOWLEDGE.md for the protocol.
roundtrip.py checks this file against the captured samples.
"""
from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from datetime import time
from enum import IntEnum

# Timings (µs). Spec values, plus this remote's gap between the two copies.
HDR_MARK, HDR_SPACE = 3400, 1750
BIT_MARK, ONE_SPACE, ZERO_SPACE = 450, 1300, 420
REPEAT_SPACE = 13200

PACKET_LEN = 18
HEADER = bytes([0x23, 0xCB, 0x26, 0x01, 0x00])


class Mode(IntEnum):
    """Byte 6 bits 5-3."""
    IFEEL = 0    # UNVALIDATED
    HEAT = 1     # UNVALIDATED: not on this (cooling-only) remote
    DRY = 2
    COOL = 3
    AUTO = 4     # UNVALIDATED: not on this (cooling-only) remote
    FAN = 7


# Byte 8 low bits repeat the mode in a different encoding
MODE_B8 = {Mode.HEAT: 0b000, Mode.DRY: 0b010, Mode.COOL: 0b110,
           Mode.AUTO: 0b000, Mode.FAN: 0b000, Mode.IFEEL: 0b110}


class Fan(IntEnum):
    """Byte 9 bits 2-0."""
    AUTO = 0
    SPEED_1 = 1
    SPEED_2 = 2
    SPEED_3 = 3
    SPEED_4 = 4
    SILENT = 5


class Vane(IntEnum):
    """Byte 9 bits 5-3 (up/down vane)."""
    AUTO = 0
    POS_1 = 1    # top
    POS_2 = 2
    POS_3 = 3
    POS_4 = 4
    POS_5 = 5    # bottom
    SWING = 7


# Byte 9 bits 7-6: a press marker, not state. 0x80 makes the unit double-beep.
B9_FLAG_MASK = 0xC0
B9_FLAG_DEFAULT = 0x40
B8_HIGH = 0x30        # wide vane is manual on this unit; remote always sends 3
B14_CLEAN = 0x04
B14_ECO = 0x20
B15_TURBO = 0x08
# Byte 13 timer bits. UNVALIDATED: spec sheet only.
TIMER_ANY, TIMER_END, TIMER_START = 0b001, 0b010, 0b100


def _to_time(units: int) -> time:
    minutes = units * 10
    return time(minutes // 60 % 24, minutes % 60)


def _to_units(t: time) -> int:
    """Wall-clock time to 10-minute units, rounding down."""
    return (t.hour * 60 + t.minute) // 10


@dataclass
class AcState:
    """Everything one packet carries, as plain values."""
    power: bool = False
    mode: Mode = Mode.COOL
    temperature: int = 24             # °C, 16-31
    fan: Fan = Fan.AUTO
    vane: Vane = Vane.AUTO
    isee: bool = False
    clean: bool = False
    eco: bool = False
    turbo: bool = False
    clock: time = time(0, 0)
    on_timer: time | None = None      # UNVALIDATED
    off_timer: time | None = None     # UNVALIDATED

    @classmethod
    def from_bytes(cls, b: bytes) -> AcState:
        """Decode a packet. Raises ValueError on values no enum defines."""
        timer = b[13] & 0x07
        return cls(
            power=bool(b[5] & 0x20),
            mode=Mode((b[6] >> 3) & 0x07),
            temperature=(b[7] & 0x0F) + 16,
            fan=Fan(b[9] & 0x07),
            vane=Vane((b[9] >> 3) & 0x07),
            isee=bool(b[6] & 0x40),
            clean=bool(b[14] & B14_CLEAN),
            eco=bool(b[14] & B14_ECO),
            turbo=bool(b[15] & B15_TURBO),
            clock=_to_time(b[10]),
            on_timer=_to_time(b[12]) if timer & TIMER_START else None,
            off_timer=_to_time(b[11]) if timer & TIMER_END else None,
        )

    def to_bytes(self, flag: int = B9_FLAG_DEFAULT) -> bytes:
        """Build the 18-byte packet, checksum included."""
        if not 16 <= self.temperature <= 31:
            raise ValueError(f"temperature {self.temperature} °C is outside 16-31")
        if flag not in (0x40, 0x80):
            raise ValueError(f"flag 0x{flag:02x} must be 0x40 or 0x80")
        b = bytearray(PACKET_LEN)
        b[0:5] = HEADER
        b[5] = 0x20 if self.power else 0x00
        b[6] = self.mode << 3 | (0x40 if self.isee else 0)
        b[7] = self.temperature - 16
        b[8] = B8_HIGH | MODE_B8[self.mode]
        b[9] = flag | self.vane << 3 | self.fan
        b[10] = _to_units(self.clock)
        if self.off_timer is not None:
            b[11] = _to_units(self.off_timer)
            b[13] |= TIMER_ANY | TIMER_END
        if self.on_timer is not None:
            b[12] = _to_units(self.on_timer)
            b[13] |= TIMER_ANY | TIMER_START
        b[14] = (B14_CLEAN if self.clean else 0) | (B14_ECO if self.eco else 0)
        b[15] = B15_TURBO if self.turbo else 0
        b[17] = sum(b[:17]) & 0xFF
        return bytes(b)


def packet_timings(packet: bytes, repeats: int = 2) -> list[int]:
    """Mark/space timings (µs). Always send both copies (repeats=2)."""
    frame = [HDR_MARK, HDR_SPACE]
    for byte in packet:
        for n in range(8):              # LSB first
            frame += [BIT_MARK, ONE_SPACE if byte >> n & 1 else ZERO_SPACE]
    frame.append(BIT_MARK)
    timings = list(frame)
    for _ in range(repeats - 1):
        timings += [REPEAT_SPACE] + frame
    return timings


def tuya_compress(data: bytes) -> bytes:
    """Greedy LZ77 in Tuya's block format (inverse of the decompressor)."""
    max_dist = 1 << 13
    max_len = 7 + 255 + 2
    out = bytearray()
    literals = bytearray()

    def flush_literals() -> None:
        for k in range(0, len(literals), 32):
            chunk = literals[k:k + 32]
            out.append(len(chunk) - 1)
            out.extend(chunk)
        literals.clear()

    i = 0
    while i < len(data):
        best_len = best_dist = 0
        for j in range(max(0, i - max_dist), i):
            n = 0
            while i + n < len(data) and n < max_len and data[j + n] == data[i + n]:
                n += 1
            if n > best_len:
                best_len, best_dist = n, i - j
        if best_len >= 3:
            flush_literals()
            length, dist = best_len - 2, best_dist - 1
            if length < 7:
                out.append(length << 5 | dist >> 8)
            else:
                out.append(7 << 5 | dist >> 8)
                out.append(length - 7)
            out.append(dist & 0xFF)
            i += best_len
        else:
            literals.append(data[i])
            i += 1
    flush_literals()
    return bytes(out)


def encode_timings(timings: list[int]) -> str:
    """Timings to a compressed Zigbee2MQTT ir_code_to_send string.

    Always compressed: the UFO-R11 path ignores long (uncompressed) codes.
    """
    raw = struct.pack(f"<{len(timings)}H", *timings)
    return base64.b64encode(tuya_compress(raw)).decode()


def encode(state: AcState, flag: int = B9_FLAG_DEFAULT) -> str:
    """AcState to a Zigbee2MQTT ir_code_to_send string (both copies)."""
    return encode_timings(packet_timings(state.to_bytes(flag)))
