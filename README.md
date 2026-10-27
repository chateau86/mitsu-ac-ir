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
- **Temperature offset:** for a unit that doesn't hold the temperature it's
  set to. It's added to the target before sending: if the unit keeps the
  room at 25 °C when set to 27 °C, use **+2**. You then set the room
  temperature you want in Home Assistant, and the unit is sent 27. Home
  Assistant's allowed range shifts to match (14–29 °C with +2). Leave it at 0
  for an accurate unit.

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

Every command carries the full state, power included. So while Home
Assistant thinks the AC is off:

- Changing a setting (temperature, fan, vane, Clean, or turning Turbo or Eco
  off) only remembers it. It's sent with the next command that turns the AC
  on. This way a unit switched on with the physical remote never gets
  turned off by accident.
- Turning **Turbo** or **Eco** on (switch or preset) also turns the AC on.
  **Clean** doesn't: like on the remote, it's a persistent setting that
  waits for the next command.
- **Turn off** always sends, even if Home Assistant already thinks it's off,
  so you can always force the unit off.

### Limits

- **Assumed state.** IR is one-way. Home Assistant shows what it last sent,
  not what the unit is actually doing. The state survives restarts, and
  nothing is sent at startup.
- **Home Assistant is just another remote.** Like the physical remotes
  (which don't sync with each other either), each one keeps its own
  settings, and any press sends all of them, overriding whatever was set
  before. Home Assistant can't hear the other remotes, so its card can show
  stale settings after someone uses one.
- **IR can't target one unit.** The packet has no unit address, so a unit
  obeys any remote or blaster it can see. With several units, aim or shield
  each blaster so only its own unit receives it; that's a physical fix, not
  something the integration can do.
- Only tested on one MSXY-FP18VG (non-K) with its factory remote. Heat, auto,
  i-feel and the timers aren't supported.

### Development

- `python roundtrip.py` checks the integration's encoder
  (`custom_components/mitsubishi_ac_ir/protocol.py`) against the captured
  remote codes in `test.py`.
- The research scripts at the repo root (`ir_decode.py`, `mitsu_ir.py`,
  `jitter.py`) may use extra libraries, such as matplotlib. Nothing under
  `custom_components/` may: see PLAN.md.
