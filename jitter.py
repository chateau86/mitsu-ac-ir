"""Timing-distortion tests, for the parser and for the AC unit itself.

    python jitter.py [JITTER]           # parser check (default 0.2)
    python jitter.py --blast [JITTER]   # print distorted codes to blast at the unit

--blast encodes BLAST_STATE with each distortion below, so the unit's own
receiver can be tested against a sloppy blaster.

Parser check: check the parser still decodes captures when their timings
are distorted.

Every sample in test.py, plus a generated code, is distorted several ways
and must still decode to the same 18 bytes:

- random: each edge independently scaled by up to +-JITTER
- all long / all short: every edge scaled by +JITTER / -JITTER (blaster
  clock running slow or fast)
- marks long, spaces short (and the reverse): typical IR receiver bias,
  where the demodulator stretches marks and eats into spaces

Then it sweeps the worst case (marks long, spaces short) to find where
decoding actually breaks.
"""
import random
import sys
from datetime import time

import test
from ir_decode import decode_ir, encode_ir
from mitsu_ir import AcState, Fan, Vane, packet_timings, parse

JITTER = 0.2
RANDOM_TRIALS = 200
SEED = 1234

# Same target as blast code A; start the unit from 22 °C, fan 4, vane pos 5
BLAST_STATE = AcState(power=True, temperature=26, fan=Fan.SPEED_2,
                      vane=Vane.POS_1, clock=time(16, 0))


def samples() -> dict[str, list[int]]:
    out = {n: decode_ir(v) for n, v in vars(test).items()
           if n.isupper() and isinstance(v, str) and len(v) > 100}
    state = AcState(power=True, temperature=26, fan=Fan.SPEED_2, vane=Vane.POS_1)
    out["(generated)"] = packet_timings(state.to_packet())
    return out


def scale(timings: list[int], mark: float, space: float) -> list[int]:
    """Scale marks (even indexes) and spaces (odd indexes)."""
    return [min(65535, round(t * (mark if i % 2 == 0 else space)))
            for i, t in enumerate(timings)]


def decodes_to(timings: list[int], expected: bytes) -> bool:
    packet, _ = parse(timings)
    return packet is not None and packet.raw == expected


def distortions(j: float, rng: random.Random):
    yield "all long", lambda t: scale(t, 1 + j, 1 + j)
    yield "all short", lambda t: scale(t, 1 - j, 1 - j)
    yield "marks long, spaces short", lambda t: scale(t, 1 + j, 1 - j)
    yield "marks short, spaces long", lambda t: scale(t, 1 - j, 1 + j)
    for n in range(RANDOM_TRIALS):
        yield f"random #{n}", lambda t: [round(x * rng.uniform(1 - j, 1 + j)) for x in t]


def blast(j: float) -> int:
    """Print BLAST_STATE encoded with each fixed distortion plus one random one."""
    clean = packet_timings(BLAST_STATE.to_packet())
    expected = BLAST_STATE.to_packet().raw
    cases = [(label, fn) for label, fn in distortions(j, random.Random(SEED))
             if not label.startswith("random #") or label == "random #0"]
    for n, (label, distort) in enumerate(cases, 1):
        timings = distort(clean)
        assert decodes_to(timings, expected), label  # our parser agrees on the bytes
        print(f"J{n}: {label} (+-{j:.0%})\n{encode_ir(timings)}\n")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--blast":
        return blast(float(args[1]) if len(args) > 1 else JITTER)
    j = float(args[0]) if args else JITTER
    rng = random.Random(SEED)
    failures = 0
    checked = 0
    for name, timings in samples().items():
        expected = parse(timings)[0].raw
        for label, distort in distortions(j, rng):
            checked += 1
            if not decodes_to(distort(timings), expected):
                failures += 1
                print(f"FAIL  {name}: {label}")
    print(f"+-{j:.0%}: {checked} distorted signals, {failures} failed")

    # Find the breaking point of the worst case, across all samples
    for pct in range(0, 61):
        d = pct / 100
        if not all(decodes_to(scale(t, 1 + d, 1 - d), parse(t)[0].raw)
                   for t in samples().values()):
            print(f"Marks long / spaces short first fails at +-{pct}%")
            break
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
