"""Check the encoder against every captured sample in test.py.

For each sample: decode -> AcState -> to_packet (keeping the capture's byte 9
flag) must give back the captured 18 bytes, and encode -> decode must give
back that packet in both frames.

    python roundtrip.py
"""
import sys

import test
from ir_decode import decode_ir, encode_ir, tuya_compress, tuya_decompress
from mitsu_ir import B9_FLAG_MASK, AcState, Mode, encode, parse, split_frames


def samples() -> dict[str, str]:
    return {n: v for n, v in vars(test).items()
            if n.isupper() and isinstance(v, str) and len(v) > 100}


def check(name: str, code: str) -> list[str]:
    problems = []
    packet, _ = parse(decode_ir(code))
    if packet is None or not packet.checksum_ok:
        return ["capture has no valid frame"]
    state = AcState.from_packet(packet)
    flag = packet.raw[9] & B9_FLAG_MASK

    # Packet level: the state must rebuild the exact captured bytes
    rebuilt = state.to_packet(flag).raw
    if rebuilt != packet.raw:
        diff = [i for i in range(len(rebuilt)) if rebuilt[i] != packet.raw[i]]
        detail = ", ".join(f"b{i} {packet.raw[i]:02x}->{rebuilt[i]:02x}" for i in diff)
        if state.mode == Mode.IFEEL and set(diff) <= {7, 17}:
            detail += " (expected: i-feel offset bits aren't modelled)"
        problems.append(f"packet differs: {detail}")

    # Signal level: our code must decode to the rebuilt packet, twice
    ours = encode(state, flag)
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
        raw = tuya_decompress(__import__("base64").b64decode(code))
        assert tuya_decompress(tuya_compress(raw)) == raw, f"compress {name}"

    failed = 0
    for name, code in samples().items():
        problems = check(name, code)
        expected = all("expected:" in p for p in problems)
        status = "ok" if not problems else ("ok*" if expected else "FAIL")
        failed += status == "FAIL"
        print(f"{status:<5} {name}")
        for p in problems:
            print(f"        {p}")

    example = encode(AcState(power=True))
    print(f"\n{len(samples())} samples, {failed} failed. "
          f"Encoded code length: {len(example)} chars "
          f"(captures: {min(map(len, samples().values()))}-"
          f"{max(map(len, samples().values()))})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
