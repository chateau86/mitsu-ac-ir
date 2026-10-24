import base64, struct

def tuya_decompress(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        h = data[i]; i += 1
        L, D = h >> 5, h & 0x1F
        if L == 0:                      # literal run
            out += data[i:i + D + 1]
            i += D + 1
        else:                           # back-reference
            if L == 7:
                L += data[i]; i += 1
            dist = ((D << 8) | data[i]) + 1; i += 1
            for _ in range(L + 2):
                out.append(out[-dist])
    return bytes(out)

def tuya_compress(data: bytes) -> bytes:
    """Inverse of tuya_decompress: greedy LZ77 in Tuya's block format."""
    MAX_DIST = 1 << 13          # 5 + 8 distance bits
    MAX_LEN = 7 + 255 + 2       # L = 7 plus an extra length byte, plus 2
    out = bytearray()
    literals = bytearray()

    def flush_literals():
        for k in range(0, len(literals), 32):
            chunk = literals[k:k + 32]
            out.append(len(chunk) - 1)
            out.extend(chunk)
        literals.clear()

    i = 0
    while i < len(data):
        best_len = best_dist = 0
        for j in range(max(0, i - MAX_DIST), i):
            n = 0
            # Overlapping matches are fine: the decompressor copies byte by byte
            while i + n < len(data) and n < MAX_LEN and data[j + n] == data[i + n]:
                n += 1
            if n > best_len:
                best_len, best_dist = n, i - j
        if best_len >= 3:
            flush_literals()
            L, d = best_len - 2, best_dist - 1
            if L < 7:
                out.append(L << 5 | d >> 8)
            else:
                out.append(7 << 5 | d >> 8)
                out.append(L - 7)
            out.append(d & 0xFF)
            i += best_len
        else:
            literals.append(data[i])
            i += 1
    flush_literals()
    return bytes(out)

def decode_ir(code: str) -> list[int]:
    raw = tuya_decompress(base64.b64decode(code))
    return list(struct.unpack(f"<{len(raw) // 2}H", raw))

def encode_ir(timings: list[int], compress: bool = True) -> str:
    """Timings (µs) to a zigbee2mqtt ir_code_to_send string.

    compress=False sends literal blocks only (about 1.6 kB of base64). The
    UFO-R11 setup ignored codes that long, so it's for debugging only.
    """
    raw = struct.pack(f"<{len(timings)}H", *timings)
    if not compress:
        blocks = bytearray()
        for k in range(0, len(raw), 32):
            blocks.append(len(raw[k:k + 32]) - 1)
            blocks.extend(raw[k:k + 32])
        return base64.b64encode(bytes(blocks)).decode()
    return base64.b64encode(tuya_compress(raw)).decode()

def plot_ir(timings: list[int], title: str = "IR signal") -> None:
    import matplotlib.pyplot as plt  # only needed for plotting

    # Edge times (ms) and the LED level after each edge: on, off, on, off...
    t = [0.0]
    levels = []
    for i, dur in enumerate(timings):
        levels.append(1 if i % 2 == 0 else 0)
        t.append(t[-1] + dur / 1000)
    levels.append(0)  # LED ends off

    fig, ax = plt.subplots(figsize=(14, 3))
    ax.step(t, levels, where="post", linewidth=1)
    ax.fill_between(t, levels, step="post", alpha=0.3)
    ax.set_yticks([0, 1], ["off", "on"])
    ax.set_ylim(-0.2, 1.3)
    ax.set_xlabel("time (ms)")
    ax.set_title(f"{title}  ({len(timings)} edges, {t[-1]:.1f} ms total)")
    ax.grid(axis="x", alpha=0.3)

    # Label each segment's duration when there are few enough to stay readable
    if len(timings) <= 80:
        for i, dur in enumerate(timings):
            mid = (t[i] + t[i + 1]) / 2
            ax.text(mid, 1.08 if i % 2 == 0 else 0.08, str(dur),
                    ha="center", fontsize=6, rotation=90)

    fig.tight_layout()
    plt.show()
