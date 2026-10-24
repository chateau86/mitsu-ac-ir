"""Parse raw Mitsubishi HVAC IR timings into the 18-byte packet and AcState.

Protocol reference: r45635 HVAC-IR-Control "Mitsubishi IR Packet Data" v1.1.
Timings are matched with wide windows (split at the midpoint between the
expected values) because cheap blasters/receivers drift by 10-20%.
"""
from dataclasses import dataclass, field, fields
from datetime import time
from enum import IntEnum

from ir_decode import decode_ir

# Nominal timings (µs) from the spec, for reference
HDR_MARK, HDR_SPACE = 3400, 1750
BIT_MARK, ONE_SPACE, ZERO_SPACE = 450, 1300, 420
RPT_SPACE = 17100

# Loose classification thresholds (µs)
HDR_MARK_MIN = 2000                            # header mark if longer than this
HDR_SPACE_MIN = 1000                           # space after a header mark
BIT_MARK_RANGE = (150, 1000)                   # anything else is suspicious
ONE_ZERO_SPLIT = (ONE_SPACE + ZERO_SPACE) / 2  # ~860: above = 1, below = 0
ONE_SPACE_MAX = 2500                           # longer than this = end of frame

PACKET_LEN = 18
HEADER = bytes([0x23, 0xCB, 0x26, 0x01, 0x00])


class Mode(IntEnum):
    """Byte 6 bits 5-3. COOL, DRY and FAN are confirmed from captures."""
    IFEEL = 0    # UNVALIDATED: one capture only, not used by the owner (see AcState)
    HEAT = 1     # UNVALIDATED: not on this (cooling-only) remote; spec value
    DRY = 2
    COOL = 3
    AUTO = 4     # UNVALIDATED: not on this (cooling-only) remote; spec value
    FAN = 7      # fan-only; not on the spec sheet, confirmed by capture


# Byte 8 low bits repeat the mode in a different encoding. COOL, DRY and FAN
# are confirmed by captures; HEAT and AUTO come from the spec sheet only
# and won't be tested (not on this remote).
# IFEEL (unvalidated) sent 0b110 every time, even when entered from fan mode.
MODE_B8 = {Mode.HEAT: 0b000, Mode.DRY: 0b010, Mode.COOL: 0b110,
           Mode.AUTO: 0b000, Mode.FAN: 0b000, Mode.IFEEL: 0b110}


class Fan(IntEnum):
    """Byte 9 bits 2-0. Values are the wire bits; all confirmed by capture."""
    AUTO = 0
    SPEED_1 = 1
    SPEED_2 = 2
    SPEED_3 = 3
    SPEED_4 = 4
    SILENT = 5   # not on the spec sheet


class Vane(IntEnum):
    """Vertical (up/down) vane, byte 9 bits 5-3. All confirmed by capture."""
    AUTO = 0
    POS_1 = 1    # top
    POS_2 = 2
    POS_3 = 3
    POS_4 = 4
    POS_5 = 5    # bottom
    SWING = 7


# Byte 9 bits 7-6: always exactly one set (10 or 01). It's a marker for the
# press that sent the packet, not AC state: FAN_3 and VANE_AUTO_AGAIN have
# identical bytes 0-16 but different flags. 10 shows up for one press (fan
# or vane stepped onto auto, entering i-feel, and a few others) and is 01
# for everything else. Send 01. Whether the unit cares is still to be tested
# by blasting both variants. See KNOWLEDGE.md.
B9_FLAG_MASK = 0xC0
B9_FLAGS = {0x80: "10", 0x40: "01"}

# Byte 8 high nibble is the wide (left/right) vane in the spec. This unit's
# left/right vane is manual only, and the remote always sends 3 ("middle").
B8_HIGH = 0x30


# Byte 13 low bits: bit 0 = any timer, bit 1 = off (end), bit 2 = on (start).
# UNVALIDATED: taken from the spec sheet; no timer captures (not used by the owner).
TIMER_ANY, TIMER_END, TIMER_START = 0b001, 0b010, 0b100

# Flag bits confirmed by captures
B7_IFEEL = 0x40   # UNVALIDATED: set in the one i-feel capture
B14_CLEAN = 0x04
B14_ECO = 0x20
B15_TURBO = 0x08  # the spec sheet's "install position: left" bit on the MSZ-FD25


@dataclass
class Frame:
    """One header-delimited burst: its bits and any timing warnings."""
    start_index: int
    bits: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def data(self) -> bytes:
        """Bits packed LSB-first into bytes (whole bytes only)."""
        out = bytearray()
        for i in range(0, len(self.bits) - 7, 8):
            out.append(sum(b << n for n, b in enumerate(self.bits[i:i + 8])))
        return bytes(out)

    @property
    def complete(self) -> bool:
        return len(self.bits) >= PACKET_LEN * 8


def split_frames(timings: list[int]) -> list[Frame]:
    """Find each header mark/space pair and read the bits that follow."""
    frames = []
    i = 0
    while i < len(timings) - 1:
        if i % 2 == 0 and timings[i] > HDR_MARK_MIN and timings[i + 1] > HDR_SPACE_MIN:
            frame = Frame(start_index=i)
            i += 2
            # Read mark/space pairs until a long gap, another header, or the end
            while i < len(timings):
                mark = timings[i]
                if mark > HDR_MARK_MIN:
                    break
                if not BIT_MARK_RANGE[0] <= mark <= BIT_MARK_RANGE[1]:
                    frame.warnings.append(f"edge {i}: odd mark {mark} µs")
                if i + 1 >= len(timings):
                    i += 1                      # trailing mark, capture ends
                    break
                space = timings[i + 1]
                if space > ONE_SPACE_MAX:
                    i += 2                      # trailing mark + inter-frame gap
                    break
                frame.bits.append(1 if space > ONE_ZERO_SPLIT else 0)
                i += 2
            frames.append(frame)
        else:
            i += 1
    return frames


def _name(enum_cls: type[IntEnum], value: int) -> str:
    try:
        return enum_cls(value).name.lower()
    except ValueError:
        return f"? ({value})"


def _hhmm(units: int) -> str:
    """Byte 10-12 time: 10-minute units since midnight."""
    minutes = units * 10
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _b8_check(b: bytes) -> str:
    """Note when byte 8's mode bits disagree with byte 6's mode."""
    try:
        expected = MODE_B8[Mode((b[6] >> 3) & 0x07)]
    except (ValueError, KeyError):
        return ""
    return "" if b[8] & 0x07 == expected else f" (expected {expected:03b})"


def _to_time(units: int) -> time:
    minutes = units * 10
    return time(minutes // 60 % 24, minutes % 60)


@dataclass
class MitsubishiPacket:
    """The raw 18-byte packet, with a byte-by-byte view like the spec table."""
    raw: bytes

    @property
    def checksum_ok(self) -> bool:
        return sum(self.raw[:17]) & 0xFF == self.raw[17]

    @property
    def header_ok(self) -> bool:
        return self.raw[:5] == HEADER

    def fields(self) -> list[tuple[int, str, str]]:
        """(byte index, field name, decoded value) rows, like the spec table."""
        b = self.raw
        flag = b[9] & B9_FLAG_MASK
        b8_high = b[8] & 0xF0
        timer = b[13] & 0x07
        if timer == 0:
            timer_str = "none"
        elif timer & TIMER_ANY and timer & (TIMER_START | TIMER_END):
            timer_str = "+".join(n for bit, n in ((TIMER_START, "start"), (TIMER_END, "end"))
                                 if timer & bit)
        else:
            timer_str = f"? ({timer:03b})"
        return [
            (0, "header", "ok" if self.header_ok else f"UNEXPECTED {b[:5].hex(' ')}"),
            (5, "power", "on" if b[5] & 0x20 else "off"),
            (6, "mode", _name(Mode, (b[6] >> 3) & 0x07)),
            (6, "i-see", "on" if b[6] & 0x40 else "off"),
            (7, "temperature", f"{(b[7] & 0x0F) + 16} °C"),
            (7, "i-feel flag", "on" if b[7] & B7_IFEEL else "off"),
            (8, "mode (b8)", f"{b[8] & 0x07:03b}" + _b8_check(b)),
            (8, "high nibble", f"0x{b8_high:02x}" + ("" if b8_high == B8_HIGH
                                                       else f" (expected 0x{B8_HIGH:02x})")),
            (9, "fan", _name(Fan, b[9] & 0x07)),
            (9, "vane", _name(Vane, (b[9] >> 3) & 0x07)),
            (9, "flag (7-6)", B9_FLAGS.get(flag, f"{flag >> 6:02b} (never seen)")),
            (10, "clock", _hhmm(b[10])),
            (11, "end time", _hhmm(b[11]) if b[11] else "-"),
            (12, "start time", _hhmm(b[12]) if b[12] else "-"),
            (13, "timer mode", timer_str),
            (14, "clean", "on" if b[14] & B14_CLEAN else "off"),
            (14, "eco", "on" if b[14] & B14_ECO else "off"),
            (15, "turbo", "on" if b[15] & B15_TURBO else "off"),
            (16, "constant", f"0x{b[16]:02x}" + ("" if b[16] == 0 else " (expected 0x00)")),
            (17, "checksum", f"0x{b[17]:02x} " + ("ok" if self.checksum_ok
                                                 else f"BAD (expected 0x{sum(b[:17]) & 0xFF:02x})")),
        ]

    def table(self) -> str:
        lines = [f"{'byte':>4}  {'hex':>4}  {'bits':>8}  {'field':<17} value",
                 "-" * 52]
        last = None
        for idx, name, value in self.fields():
            if idx != last:
                byte = self.raw[idx]
                prefix = f"{idx:>4}  0x{byte:02x}  {byte:08b}"
                last = idx
            else:
                prefix = " " * 22
            lines.append(f"{prefix}  {name:<17} {value}")
        return "\n".join(lines)


@dataclass
class AcState:
    """What the remote lets you set, as plain values.

    Confirmed by captures: power, mode (cool, dry, fan), temperature, fan, vane,
    clean, eco, turbo, clock.

    NOT VALIDATED (the owner doesn't use these, so no captures are planned):
    i-feel mode, on/off timers, and heat/auto modes (not on this cooling-only
    remote). They decode from the spec sheet and a few i-feel captures;
    don't rely on them. i-see is also spec-only so far
    (every capture had it off).

    There's no wide (left/right) vane field: on this unit it's manual, and
    the remote always sends the same value (B8_HIGH). Byte 9's bits 7-6 flag
    isn't a field either: it marks the press, not state (see B9_FLAG_MASK).
    """
    power: bool = False
    mode: Mode = Mode.COOL
    temperature: int = 24             # °C, 16-31
    fan: Fan = Fan.AUTO
    vane: Vane = Vane.AUTO
    isee: bool = False
    clean: bool = False
    eco: bool = False
    turbo: bool = False
    clock: time = time(0, 0)          # 10-minute resolution on the wire
    on_timer: time | None = None      # UNVALIDATED; "start time" in the spec
    off_timer: time | None = None     # UNVALIDATED; "end time" in the spec

    @classmethod
    def from_packet(cls, packet: MitsubishiPacket) -> "AcState":
        """Decode a packet. Raises ValueError on values no enum defines."""
        b = packet.raw
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

    def __str__(self) -> str:
        parts = []
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, IntEnum):
                v = v.name.lower()
            elif isinstance(v, time):
                v = v.strftime("%H:%M")
            parts.append(f"{f.name}={v}")
        return "AcState(" + ", ".join(parts) + ")"


def parse(timings: list[int]) -> tuple[MitsubishiPacket | None, list[Frame]]:
    """Return the packet from the first complete frame with a good checksum.

    Falls back to the first complete frame if none pass the checksum.
    All frames are returned too, for diagnostics.
    """
    frames = split_frames(timings)
    complete = [f for f in frames if f.complete]
    for f in complete:
        packet = MitsubishiPacket(f.data[:PACKET_LEN])
        if packet.checksum_ok:
            return packet, frames
    if complete:
        return MitsubishiPacket(complete[0].data[:PACKET_LEN]), frames
    return None, frames


def report(code: str, title: str = "") -> None:
    timings = decode_ir(code)
    packet, frames = parse(timings)
    if title:
        print(f"=== {title} ===")
    for n, f in enumerate(frames):
        status = "complete" if f.complete else f"TRUNCATED at {len(f.bits)} bits"
        print(f"frame {n}: edge {f.start_index}, {status}, bytes {f.data.hex(' ')}")
        if not f.complete:
            continue  # receiver cut the capture short; the tail edges are junk
        for w in f.warnings:
            print(f"  warning: {w}")
    if len(frames) >= 2 and frames[0].complete:
        # The repeat should match frame 0 for as far as it got. Compare whole
        # bytes only: the last few edges of a truncated capture are often junk.
        repeat = frames[1].data
        if repeat != frames[0].data[:len(repeat)]:
            print("  warning: frame 1 differs from frame 0")
    if packet is None:
        print("no complete frame found")
    else:
        print(packet.table())
        try:
            print(AcState.from_packet(packet))
        except ValueError as e:
            print(f"can't decode as AcState: {e}")
    print()
