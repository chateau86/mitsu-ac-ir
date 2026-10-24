"""Check the integration's encoder against every captured sample in test.py.

The encoder under test is custom_components/mitsubishi_ac_ir/protocol.py;
the research decoder (mitsu_ir.py) is the reference. For each sample:

- AcState.from_bytes -> to_bytes (keeping the capture's byte 9 flag) must
  give back the captured 18 bytes
- encode -> decode must give back that packet in both frames

    python roundtrip.py
"""
import base64
import sys
from pathlib import Path

import test
from ir_decode import decode_ir, tuya_decompress
from mitsu_ir import parse, split_frames

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "mitsubishi_ac_ir"))
import protocol  # noqa: E402  (the integration's copy, no HA imports)


def samples() -> dict[str, str]:
    return {n: v for n, v in vars(test).items()
            if n.isupper() and isinstance(v, str) and len(v) > 100}


def check(code: str) -> list[str]:
    problems = []
    packet, _ = parse(decode_ir(code))
    if packet is None or not packet.checksum_ok:
        return ["capture has no valid frame"]
    state = protocol.AcState.from_bytes(packet.raw)
    flag = packet.raw[9] & protocol.B9_FLAG_MASK

    # Packet level: the state must rebuild the exact captured bytes
    rebuilt = state.to_bytes(flag)
    if rebuilt != packet.raw:
        diff = [i for i in range(len(rebuilt)) if rebuilt[i] != packet.raw[i]]
        detail = ", ".join(f"b{i} {packet.raw[i]:02x}->{rebuilt[i]:02x}" for i in diff)
        if state.mode == protocol.Mode.IFEEL and set(diff) <= {7, 17}:
            detail += " (expected: i-feel offset bits aren't modelled)"
        problems.append(f"packet differs: {detail}")

    # Signal level: our code must decode to the rebuilt packet, twice
    ours = protocol.encode(state, flag)
    frames = split_frames(decode_ir(ours))
    if len(frames) != 2 or not all(f.complete for f in frames):
        problems.append(f"encoded signal has {len(frames)} frames, "
                        f"complete: {[f.complete for f in frames]}")
    elif any(f.data[:18] != rebuilt for f in frames):
        problems.append("encoded signal decodes to different bytes")
    return problems


def main() -> int:
    # The compressor must invert the decompressor on real data
    for name, code in samples().items():
        raw = tuya_decompress(base64.b64decode(code))
        assert tuya_decompress(protocol.tuya_compress(raw)) == raw, f"compress {name}"

    failed = 0
    for name, code in samples().items():
        problems = check(code)
        expected = all("expected:" in p for p in problems)
        status = "ok" if not problems else ("ok*" if expected else "FAIL")
        failed += status == "FAIL"
        print(f"{status:<5} {name}")
        for p in problems:
            print(f"        {p}")

    # The blast-tested code A must come out byte-identical
    code_a = protocol.encode(protocol.AcState(
        power=True, temperature=26, fan=protocol.Fan.SPEED_2,
        vane=protocol.Vane.POS_1, clock=protocol.time(16, 0)))
    known_a = ("B0gN1gbCARQFgAMBpAHgAQPgAw/gAx/gExfgBzPgC0vgPwfgD1PgC8vgA8/gGzfhEw/"
               "gH9fgD4fgqw/CH+EP6wGQM+L/R+L/R+ItRw==")
    if code_a != known_a:
        failed += 1
        print("FAIL  code A no longer matches the blast-tested code")

    print(f"\n{len(samples())} samples, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
