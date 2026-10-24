# Protocol knowledge

What we know about this AC's IR protocol so far, and how sure we are.

Hardware: MSXY-FP18VG (non-K) indoor unit, its factory remote, and a Tuya
UFO-R11 IR blaster/receiver used through zigbee2mqtt.

Reference: r45635's "Mitsubishi IR Packet Data v1.1" sheet (see README). It
documents the MSZ-GF60VE / MSZ-FD25VA, so several of its fields don't apply
to this unit or mean something else here.

## Testing rules

- **Always specify the start state for a capture test.** The AC under test is
  also the owner's only cooling, so its state between test sessions is
  whatever was comfortable, not what the last test left. Each test plan
  must list the full starting settings (power, mode, temperature, fan,
  vane, turbo/eco/clean) and how to reach them.
- The fan and vane buttons each step one setting per press and can't jump.
  Plan sequences around that, and say which intermediate presses to capture.
- Name captures by test and step (`BIGTEST_03`), and add a comment in
  `test.py` saying what was pressed.

Confidence labels used below:

- **confirmed**: seen in our captures, changing as expected
- **spec only**: from the reference sheet, not yet seen in a capture
- **UNVALIDATED**: the owner doesn't use the feature, so it won't be tested

## 1. zigbee2mqtt / UFO-R11 code format

`learned_ir_code` and `ir_code_to_send` are strings built in three layers:

1. **Base64**, wrapping
2. **Tuya's compression** (a FastLZ / LZ77 variant), wrapping
3. **Raw timings**: little-endian `uint16` durations in µs. They alternate
   mark (LED on, carrier bursting) and space (LED off), starting with a mark.

The carrier frequency (about 38 kHz) isn't stored.

Decompression reads a stream of blocks. Each block starts with a header
byte `h`, split into `L = h >> 5` and `D = h & 0x1F`:

- `L == 0`: a literal run. Copy the next `D + 1` bytes.
- otherwise: a back-reference.
  - If `L == 7`, add the next byte to `L`.
  - The length is `L + 2`.
  - The distance is `((D << 8) | next_byte) + 1`.
  - Copy byte by byte from that far back in the output (the source may
    overlap the destination).

For sending, compression is optional. A stream of literal blocks only
(header byte `len - 1`, at most 32 bytes per block) is valid.

Implemented in `ir_decode.py` (`tuya_decompress`, `decode_ir`, `plot_ir`).

**Capture quirk:** the receiver stops recording partway through the
second frame (after about 97–122 bits). The last few edges of a capture are
junk (marks of about 100 µs). Only frame 1 is ever complete, and that's
enough to decode. When we generate codes, we'll build both frames
ourselves.

## 2. Framing and timing

| Symbol | Mark (µs) | Space (µs) | Notes |
|---|---|---|---|
| Header | 3400 | 1750 | captured: ~3400–3460 / ~1770–1810 |
| `1` bit | 450 | 1300 | captured: ~430–500 / ~1360 |
| `0` bit | 450 | 420 | captured: ~430–500 / ~430 |
| Inter-frame gap | 440 | 17100 (spec) | **this remote: ~13200** |

- Pulse-distance coding: the mark is constant, and the space length is the
  bit value.
- One frame is: header, then 18 bytes × 8 bits = 144 bits, then a trailing
  mark.
- The whole frame is sent **twice**, separated by the gap.
- Bits are **LSB-first** within each byte on the wire. The spec sheet's
  per-byte bit diagrams are drawn MSB-first, even though their columns are
  labelled 0–7.

The parser (`mitsu_ir.split_frames`) matches timing loosely, because the
cheap blaster jitters:

| Thing | Rule |
|---|---|
| Header | mark > 2000 µs, then space > 1000 µs |
| Bit value | space > 860 µs (midpoint of 420 and 1300) is a 1, otherwise a 0 |
| End of frame | space > 2500 µs |
| Odd marks | marks outside 150–1000 µs give a warning, for complete frames only |

## 3. Packet layout (18 bytes)

Bit numbers are normal (bit 7 = `0x80`).

| Byte | Content | Status |
|---|---|---|
| 0–4 | header `23 CB 26 01 00` | confirmed |
| 5 | power: `0x20` on, `0x00` off | confirmed |
| 6 | mode in bits 5–3; i-see in bit 6 | see below |
| 7 | temperature in the low nibble (°C − 16), 16–31 °C | confirmed (16 and 31 tested) |
| 8 | low 3 bits: mode again; high nibble: always `0x3` | see below |
| 9 | fan bits 2–0, vane bits 5–3, flag bits 7–6 | see below |
| 10 | clock, in 10-minute units since midnight (14:20 → `0x56`) | confirmed |
| 11 | off-timer ("end") time, same units | spec only, UNVALIDATED |
| 12 | on-timer ("start") time, same units | spec only, UNVALIDATED |
| 13 | timer mode, low 3 bits: `000` none, `101` start, `011` end, `111` both | spec only, UNVALIDATED |
| 14 | `0x04` clean, `0x20` eco | confirmed |
| 15 | `0x08` turbo | confirmed |
| 16 | `0x00` | confirmed |
| 17 | checksum: sum of bytes 0–16, mod 256 | confirmed (all captures valid) |

### Mode (byte 6 bits 5–3, byte 8 bits 2–0)

| Mode | Byte 6 bits 5–3 | Byte 8 low bits | Status |
|---|---|---|---|
| heat | `001` (`0x08`) | `000` | spec only, UNVALIDATED (not on remote) |
| dry | `010` (`0x10`) | `010` | confirmed (BIGTEST_03) |
| cool | `011` (`0x18`) | `110` | confirmed |
| auto | `100` (`0x20`) | `000` | spec only, UNVALIDATED (not on remote) |
| fan-only | `111` (`0x38`) | `000` | confirmed (not on the spec sheet) |
| i-feel | `000` | `110` in the one capture | UNVALIDATED |

- **i-feel** has byte 6 = `0x00`. Byte 8 keeps `110` even when entered
  from fan mode (BIGTEST_05), so `110` is i-feel's own value, not carried
  over. Byte 7 bits 6–5 change with i-feel up/down, while the temperature
  nibble stays at 24 °C. In BIGTEST_05–09 the presses were enter, up, up,
  down, up, and byte 7 went `0x08`, `0x28`, `0x68`, `0x48`, `0x28`. That
  isn't a simple counter; it might be a cycling comfort offset. It's not
  being investigated further.
- **Heat and auto** aren't on this remote: the unit is a cooling-only
  Singapore install. Their values are from the spec sheet and won't be
  tested.
- **i-see** (byte 6 bit 6) is spec only. Every capture had it clear.

### Byte 8 high nibble

The spec sheet says this is the wide (left/right) vane. On this unit the
left/right vane is **manual only**, and the remote always sends `0x3`
("middle"). Treat it as a constant (`B8_HIGH = 0x30`).

### Fan (byte 9 bits 2–0), confirmed

| Value | Fan |
|---|---|
| `000` | auto |
| `001`–`100` | speeds 1–4 |
| `101` | silent (not on the spec sheet) |

Turbo captures show fan `000`. Turbo probably overrides the fan.

### Vane, up/down (byte 9 bits 5–3), confirmed

| Value | Vane |
|---|---|
| `000` | auto |
| `001`–`101` | positions 1 (top) to 5 (bottom) |
| `111` | swing |

### Byte 9 flag (bits 7–6): a press marker, not state

- Exactly one of the two bits is always set (`10` or `01`) in all 45
  captures.
- **It isn't a function of the packet at all.** FAN_3 and
  VANE_AUTO_AGAIN have identical bytes 0–16, clock included, but different
  flags. No parity or sum rule over the packet predicts it. The remote sets
  it from what was just pressed.
- **It doesn't stick.** It's `10` for one press, and the next press (even
  temp down) sends `01` again (BIGTEST_01 → 02).
- **Presses that gave `10`:** fan stepped onto auto, vane stepped onto
  auto, mode stepped into i-feel, one of four i-feel adjustments,
  temperature stepped to 31 °C (ON_31C), and mode → fan once (FAN_MODE).
  BIGTEST_04, the same mode → fan press, gave `01`.
- **Everything else gave `01`:** temperature, mode, manual fan and vane
  steps, turbo, eco, Smart Set, and power.
- Earlier evidence: the same settings were captured with both values.

| Fan | Vane | Byte 9 | Flag | Capture |
|---|---|---|---|---|
| 3 | auto | `0x83` | `10` | VANE_AUTO, VANE_AUTO_AGAIN (vane button pressed) |
| 3 | auto | `0x43` | `01` | FAN_3, ECO (other buttons pressed) |
| auto | auto | `0x80` | `10` | FAN_AUTO |
| auto | auto | `0x40` | `01` | SMART_SET |
| auto | pos 4 | `0xA0` | `10` | ON_31C, FAN_MODE |
| auto | pos 4 | `0x60` | `01` | TURBO |

- The spec sheet and IRremoteESP8266 call bit 7 "fan auto" and bit 6 a
  "vane set" bit. Neither fits these captures.
- **For the encoder:** send `01`. It's what the remote sends for every
  ordinary press.
- **Still to test:** blast one state with `01` and again with `10`, and see
  if the unit behaves differently. Since the flag isn't state, a difference
  is unlikely.

## 4. Remote presets and quirks

- **Smart Set** is a remote-side preset. It sends ordinary settings (21 °C,
  fan auto, vane auto, flag `01`) with no special bit.
- **Clean** (byte 14 `0x04`) was on in the early captures and off after it
  was toggled. It's a normal setting, not a constant.
- The spec sheet's MSZ-FD25 options (area in byte 13, plasma in byte 15
  bit 2, install position in byte 15 bits 4–3) don't apply. Byte 15's
  `0x08`, which the sheet calls "install position: left", is turbo here.

## 5. Code layout

| File | Contents |
|---|---|
| `ir_decode.py` | Tuya base64 + compression decoder, matplotlib plotter |
| `mitsu_ir.py` | frame splitter (`split_frames`, `parse`), the raw `MitsubishiPacket` with a byte table, the user-facing `AcState` with enums, and `report()` |
| `test.py` | the captured samples (named by what was pressed), plus a small runner |

`AcState` fields: `power`, `mode`, `temperature`, `fan`, `vane`, `isee`,
`clean`, `eco`, `turbo`, `clock`, `on_timer`, `off_timer`. The timers and
`Mode.IFEEL` are marked UNVALIDATED in the code. There's no field for the
byte 9 flag or the byte 8 high nibble.

## 6. Open items

- [x] Byte 9 flag: what sets it? It's a press marker from the remote, not
  state (BIGTEST, section 3).
- [ ] Byte 9 flag: does the unit care whether it's `01` or `10`? (blast test)
- [ ] Encoder: `AcState` → 18 bytes → timings for both frames → Tuya
  base64.
- [ ] Round-trip test: decode every sample, re-encode it, and compare the
  bytes. Ignore the byte 9 flag (and so the checksum) when comparing,
  since `AcState` can't hold it.
- [ ] Jitter test: perturb sample timings by ±25% and check they still
  decode to the same bytes.
- [ ] Not planned: i-feel, timers, i-see, heat and auto modes.
