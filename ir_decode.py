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

def decode_ir(code: str) -> list[int]:
    raw = tuya_decompress(base64.b64decode(code))
    return list(struct.unpack(f"<{len(raw) // 2}H", raw))

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
