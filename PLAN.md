# Plan: Home Assistant integration

Turn this repo into a Home Assistant custom integration that controls the
AC through the existing Zigbee2MQTT IR blasters, with a climate entity per
unit. It's built for the owner's setup first. Installing it as a HACS
*custom repository* should work, but an official HACS listing isn't a goal,
and tests can be light.

See `KNOWLEDGE.md` for the protocol.

## Approach

**Option B: publish straight to Zigbee2MQTT.** The integration encodes the
full AC state with our encoder and publishes the compressed code through HA's
MQTT integration. We rejected these alternatives:

- **HA `infrared` emitter entities:** Zigbee2MQTT support for Tuya blasters
  isn't confirmed, and the emitter's own Tuya encoding might produce codes
  over the length limit.
- **SmartIR code tables:** they freeze the clock and have no turbo, eco or
  clean.
- **MQTT climate with templates:** Jinja can't do the compression.

**Known-good publish** (tested from HA's developer tools, 2026-10-24):

```yaml
action: mqtt.publish
data:
  qos: '0'
  retain: false
  topic: zigbee2mqtt/livingroom_ir/set/ir_code_to_send
  payload: <base64 code>
```

The topic is `<base topic>/<friendly name>/set/ir_code_to_send` and the
payload is the bare code, not JSON.

## Repo layout

Research files stay at the root. The integration goes alongside them:

```
custom_components/mitsubishi_ac_ir/
  manifest.json    domain, name, version, "dependencies": ["mqtt"],
                   "config_flow": true, "iot_class": "assumed_state"
  __init__.py      set up / unload a config entry, forward to platforms
  const.py         domain, config keys, defaults
  protocol.py      encoder copied from mitsu_ir.py / ir_decode.py, no HA imports:
                   enums, AcState, to_packet, packet_timings, tuya_compress, encode
  config_flow.py   setup step + options flow
  controller.py    per-unit shared state, debounce, MQTT publish
  climate.py       climate entity
  switch.py        Turbo, Eco and Clean switches
  strings.json     UI text (keep identical to translations/en.json)
  translations/en.json
hacs.json          for installing as a HACS custom repository
```

`protocol.py` is a copy because HA only loads what's inside the integration
folder. `roundtrip.py` will be pointed at it, so the copy stays tested.

## Behaviour

### One config entry per AC unit

Add the integration once per unit; there are two units, each on its own
blaster. Each entry has:

| Field | Notes |
|---|---|
| Name | e.g. "Living room AC"; names the device and its entities |
| Blaster | Zigbee2MQTT friendly name; also the entry's unique ID, so one blaster can't be added twice |
| Base topic | default `zigbee2mqtt` |
| Room temperature sensor | optional; display only (`current_temperature`) |

- **Setup page:** the blaster field is a dropdown of Zigbee2MQTT devices that
  expose `ir_code_to_send`, read from the retained
  `<base topic>/bridge/devices` message. If that can't be read, it falls
  back to a text field.
- **Options flow:** a *Configure* button changes the blaster, base topic or
  sensor without removing the unit.

### Climate entity

| Feature | Mapping |
|---|---|
| HVAC modes | `off`, `cool`, `dry`, `fan_only`. Off sends the full state with power off. |
| Target temperature | 16–31 °C, step 1 |
| Fan modes | `auto`, `1`, `2`, `3`, `4`, `silent` |
| Swing modes (vane) | `auto`, `1`–`5` (top to bottom), `swing` |
| Presets | `none`, `boost` (turbo), `eco` |
| Current temperature | from the optional room sensor |
| State | `assumed_state`, restored after HA restarts |

### Switches (same device)

- **Turbo:** synced with the `boost` preset. Open-loop: there's no timeout
  handling, even if the unit leaves turbo on its own.
- **Eco:** synced with the `eco` preset.
- **Clean:** sent as part of every state.

### Sending

- Every change builds the unit's full `AcState` and encodes it. The encoder
  always uses flag `01`, both frame copies, and compression (the length
  limit).
- `clock` is HA's local time at send time.
- **Debounce of about 1 s per unit:** several quick changes become one blast
  and one beep.
- Publish through `mqtt.async_publish` to
  `<base topic>/<blaster>/set/ir_code_to_send`, with QoS 0 and no retain.

## Steps

| # | Who | Step |
|---|---|---|
| 0 | owner | ~~Prove the HA → Zigbee2MQTT publish path~~ done (see above) |
| 1 | Claude | ~~`protocol.py`, plus `roundtrip.py` pointed at it; all 45 samples must pass~~ done |
| 2 | Claude | ~~manifest, `__init__`, `const`, config flow and options flow~~ done |
| 3 | Claude | ~~controller (state, debounce, publish), climate entity, switches~~ done |
| 4 | Claude | ~~`hacs.json`; README install and setup section~~ done |
| 5 | owner | install (copy the folder into `/config/custom_components/`, or add as a HACS custom repo), restart, add both units |
| 6 | owner | test on the real units; see below |

## Testing on the units (step 6)

Follow the testing rules in `KNOWLEDGE.md`: give each test a fixed start
state set with the real remote, never auto, on the opposite side of the
target.

1. **Setup:** both units add cleanly. The blaster dropdown lists both
   blasters, and adding the same blaster twice is refused.
2. **Basic control:** from the start state (cool, 22 °C, fan 4, vane pos 5),
   set 26 °C, fan speed 2 and vane 1 from HA. Expect a single beep, the vane
   at the top and the fan slower.
3. **Debounce:** click temperature up several times quickly. Expect one
   beep.
4. **Each setting:** each mode, each fan speed, each vane setting, and turbo,
   eco and clean on and off, from both the climate card and the switches.
5. **Off and on:** off from HA, then back on with the same settings.
6. **Restart:** restart HA. The entity should keep its last state, and
   nothing should be sent at startup.
7. **Two units:** commands for one unit must not reach the other.

## Rules for the integration code

- **No test-only or research dependencies in `custom_components/`.** No
  numpy, no matplotlib, nothing that isn't in HA already. The manifest's
  `requirements` stays empty. `protocol.py` uses only the standard library.
  The plotter in `ir_decode.py` stays out of the copy, and nothing under
  `custom_components/` imports from the root-level research scripts.
- Fan speeds and vane positions are numbered, plus their named extras
  (`auto`, `silent`, `swing`), not HA's `low`/`medium`/`high` names.

## Decisions

- Domain: `mitsubishi_ac_ir`.
- State is kept in HA's storage (`.storage/mitsubishi_ac_ir.<entry id>`) by
  a per-unit controller, shared by the climate entity and the switches.
- **Power safety (after the first live test):** every blast carries power.
  While HA thinks the unit is off, ordinary changes are stored, not sent, so
  a unit turned on with the remote isn't switched off by, say, the Turbo
  switch. Turbo or Eco on (switch or preset) also powers on; Clean doesn't
  (it's persistent on the remote). Turn off always sends (`force_send`).
- Presets are exclusive (`boost` turns eco off and the other way round);
  the Turbo and Eco switches can still turn both on.
- The options flow can change the blaster, but the entry's unique ID stays
  the original blaster name, so the duplicate check only covers setup.

## Verification so far

- `roundtrip.py`: the integration's `protocol.py` passes all 45 samples and
  reproduces the blast-tested code A exactly.
- Every module imports against Home Assistant 2026.10.3.
- Not yet run: HA's test harness (it's Linux-only; WSL here only has
  Python 3.8). The real install in step 5 is the first end-to-end run.

## Known limits (for the README)

- **HA is just another remote.** The physical remotes don't sync with each
  other or with HA; each press sends that remote's full state. Accepted.
- **No unit addressing.** A blaster controls any unit that sees it; aim or
  shield each blaster (test 7 checks this). Accepted, physical fix only.
- **Assumed state:** IR is one-way, so HA shows what it last sent, not what
  the unit is doing.
- **Only tested on the MSXY-FP18VG (non-K)** with its factory remote and a
  UFO-R11 blaster.
