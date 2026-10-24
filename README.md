Quick 'lil reverse-engineering of IR protocol for Mitsubishi AC remote

Based loosely on: https://github.com/r45635/HVAC-IR-Control/blob/4b6b7944b28ce78247f19744c272a36935bbb305/Protocol/Mitsubishi_IR_Packet_Data_v1.1-FULL.pdf

but tested against MSXY-FP18VG (non-K) AC unit + factory remote and ir blaster UFO-R11 (https://www.zigbee2mqtt.io/devices/UFO-R11.html)

Protocol notes: [KNOWLEDGE.md](KNOWLEDGE.md). Integration plan: [PLAN.md](PLAN.md).

## Home Assistant integration

`custom_components/mitsubishi_ac_ir` controls the AC through a Zigbee2MQTT IR
blaster: a climate entity per unit, plus Turbo, Eco and Clean switches. It
generates each IR command from the full AC state and publishes it to the
blaster's `ir_code_to_send`.

### Requirements

- Home Assistant 2025.2 or newer, with the MQTT integration connected to the
  same broker as Zigbee2MQTT
- A Zigbee2MQTT IR blaster that accepts `ir_code_to_send` (tested: UFO-R11)

### Install

Either:

- **HACS:** *HACS → ⋮ → Custom repositories*, add this repo's URL with type
  *Integration*, then install *Mitsubishi AC IR*, or
- **Manually:** copy `custom_components/mitsubishi_ac_ir` into your
  `/config/custom_components/`.

Then restart Home Assistant.

### Add a unit

*Settings → Devices & services → Add integration → Mitsubishi AC IR.*

- **Name:** names the device and its entities.
- **IR blaster:** picked from your Zigbee2MQTT devices that can send IR, or
  typed as the friendly name.
- **Zigbee2MQTT base topic:** usually `zigbee2mqtt`.
- **Room temperature sensor (optional):** shown as the current temperature.

Add the integration again for each unit. Each one needs its own blaster. The
*Configure* button on an entry changes its blaster, topic or sensor later.

### What you get

| Entity | Controls |
|---|---|
| Climate | off / cool / dry / fan only; 16–31 °C; fan `auto`, `1`–`4`, `silent`; vane (swing modes) `auto`, `1`–`5` (top to bottom), `swing`; presets `none`, `boost` (turbo), `eco` |
| Turbo, Eco, Clean switches | on/off; Turbo and Eco stay in sync with the presets |

Changes made within about a second are sent as one command, so the unit
beeps once. Every command also sets the unit's clock to Home Assistant's
time.

### Limits

- **Assumed state.** IR is one-way. Home Assistant shows what it last sent,
  not what the unit is actually doing. The state survives restarts, and
  nothing is sent at startup.
- **The physical remote doesn't sync with Home Assistant.** The remote keeps
  its own settings, and any button press sends all of them, overriding what
  Home Assistant set. Home Assistant can't hear the remote.
- Only tested on one MSXY-FP18VG (non-K) with its factory remote. Heat, auto,
  i-feel and the timers aren't supported.

### Development

- `python roundtrip.py` checks the integration's encoder
  (`custom_components/mitsubishi_ac_ir/protocol.py`) against the captured
  remote codes in `test.py`.
- The research scripts at the repo root (`ir_decode.py`, `mitsu_ir.py`,
  `jitter.py`) may use extra libraries, such as matplotlib. Nothing under
  `custom_components/` may: see PLAN.md.
