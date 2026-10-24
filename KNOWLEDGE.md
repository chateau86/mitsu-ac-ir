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
- **Don't use auto in a blast test's start state.** The unit might happen
  to be doing what the target asks (an auto vane resting at the top, say),
  so nothing would visibly change. Start from fixed settings on the opposite
  side of the target: vane pos 5 for a pos 1 target, fan 4 for a fan 2
  target, and a temperature a few degrees away.
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
- **Blast test (2026-10-24):** the same settings sent with each flag value,
  from a start of 22 °C, fan 4, vane pos 5:
  - `01` (code A): applied normally.
  - `10` (code B): the unit **beeped twice**. It ended in the same state as
    with A. (The vane also hesitated briefly, but the jitter test showed
    the same hesitation with ordinary codes, so it's probably mechanical
    and random, not caused by the flag.)
- So the unit does read the flag. It looks like a "double beep" request:
  the remote sets it when a press lands on auto, perhaps so you can tell by
  ear. The flag doesn't seem to change the settings applied.
- **For the encoder:** send `01`. It's what the remote sends for ordinary
  presses, and it gives a single beep.

## 4. Remote presets and quirks

- **Smart Set** is a remote-side preset. It sends ordinary settings (21 °C,
  fan auto, vane auto, flag `01`) with no special bit.
- **Clean** (byte 14 `0x04`) was on in the early captures and off after it
  was toggled. It's a normal setting, not a constant.
- The spec sheet's MSZ-FD25 options (area in byte 13, plasma in byte 15
  bit 2, install position in byte 15 bits 4–3) don't apply. Byte 15's
  `0x08`, which the sheet calls "install position: left", is turbo here.

## 5. Encoder notes

- Sends spec timings (3400/1750 header, 450 marks, 1300/420 spaces) and
  this remote's 13200 µs gap between the two frames.
- **Always send both copies of the frame** (`repeats=2`, the default).
  Blast test (2026-10-24): a single frame (`repeats=1`) was accepted, but the
  beep came late and the vane hesitated, as if the unit waits for the
  missing second copy before acting. Two copies match the real remote and
  cost nothing: the code is still about 104 characters.
- Byte 9 flag defaults to `01` (`0x40`); `to_packet(flag=0x80)` sends `10`.
- Generated codes compress to about 100 characters, because perfectly
  regular timings turn into long back-references. The UFO-R11 handles them
  fine (blast test).
- **Long codes don't work.** A ~1600-character code with perfect timing
  (`compress=False`) got no response, nor did ~1550-character ones. The
  limit is somewhere between 104 characters (works) and about 1540 (fails),
  whether in the UFO-R11 or zigbee2mqtt. So compression is required, and
  `compress=False` is only useful for debugging.
- **The physical remote keeps its own state.** After a blasted code, the
  remote's display is out of sync with the unit, and the next remote press
  sends the remote's full state, undoing the blasted settings.
- `clock` defaults to 00:00. The unit may set its clock from it; that only
  matters if its timers are used.

## 6. Code layout

| File | Contents |
|---|---|
| `ir_decode.py` | Tuya base64 + compression decoder and encoder, matplotlib plotter |
| `mitsu_ir.py` | frame splitter (`split_frames`, `parse`), the raw `MitsubishiPacket` with a byte table, the user-facing `AcState` with enums (`from_packet` / `to_packet`), `packet_timings()`, `encode()` and `report()` |
| `test.py` | the captured samples (named by what was pressed), plus a small runner |
| `roundtrip.py` | checks the encoder against every sample in `test.py` |
| `jitter.py` | checks the parser against distorted timings (default ±20%); `--blast` prints distorted codes for testing the unit |

`AcState` fields: `power`, `mode`, `temperature`, `fan`, `vane`, `isee`,
`clean`, `eco`, `turbo`, `clock`, `on_timer`, `off_timer`. The timers and
`Mode.IFEEL` are marked UNVALIDATED in the code. There's no field for the
byte 9 flag or the byte 8 high nibble.

## 7. Open items

- [x] Byte 9 flag: what sets it? It's a press marker from the remote, not
  state (BIGTEST, section 3).
- [x] Byte 9 flag: does the unit care whether it's `01` or `10`? Yes: `10`
  gives a double beep, with the same end state (blast test, section 3).
- [x] Encoder: `AcState.to_packet()` → `packet_timings()` → `encode_ir()`.
  `mitsu_ir.encode()` does all three.
- [x] Round-trip test (`roundtrip.py`): all 45 samples rebuild their exact
  bytes when given the capture's byte 9 flag. i-feel captures differ only
  in byte 7's unmodelled offset bits.
- [x] Blast test: does the unit accept generated codes? Yes, the
  compressed code works, so `compress=False` isn't needed. Vane and fan
  changes confirmed by sight and sound.
- [ ] Temperature from a generated code isn't confirmed: the unit has no
  temperature display (only two LEDs). It could be checked by blasting 16 °C
  vs 31 °C and comparing compressor behaviour or outlet air, if needed.
- [x] Jitter test (`jitter.py`): every sample plus a generated code still
  decodes to the same bytes at ±20% (random per-edge jitter, uniform
  stretch/shrink, and marks long with spaces short or the reverse). The
  worst case, marks long and spaces short, first fails at ±34%, when a `1`
  space drops below the 860 µs split. This covers the parser only, not the
  unit's own receiver.
- [x] Unit jitter test (`python jitter.py --blast`, results in
  `jitter_codes.txt`). BLAST_STATE was blasted with ±20% distortions:
  - J1 (all long), J2 (all short), J3 (marks long, spaces short) and J4
    (the reverse): **all accepted**, with a single beep. J2 and J3 showed a
    vane hesitation, which also happens at random with ordinary codes.
  - J5 (random per-edge ±20%, 1552 characters): no response. So did both
    controls: K1 (no jitter, uncompressed, 1604 characters) and K2 (random
    ±10%, 1540 characters). Since K1 has perfect timing, the **code length**
    is what failed, not the jitter. Random jitter can't be tested this way,
    because random timings don't compress.
  - Closed (2026-10-24): clock-rate error is the realistic failure for a
    cheap blaster, and ±20% of it is fine. Random per-edge jitter isn't
    tested and isn't expected.
- [x] Single-frame test: accepted, but slow to react. Always send both
  copies (section 5).
- [ ] Not planned: i-feel, timers, i-see, heat and auto modes.
