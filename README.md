# Kermi EcoTimer for Home Assistant

Local Bluetooth control of the **Kermi EcoTimer** room thermostat for electric towel
radiators (vendor app "EcoTimer", `kermi.ecotimer`). No cloud, no bridge.

## Requirements

- Home Assistant 2025.3 or newer with the Bluetooth integration
- A **connectable** Bluetooth adapter in range: the built-in adapter of the host or an
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/) (classic ESP32).
  Shelly devices only forward advertisements and cannot connect, so they do not work here.

Home Assistant picks the adapter or proxy with the best signal for every connection. The
diagnostic sensor *Bluetooth adapter* shows which one currently receives the device.

The integration keeps the connection open and reads the state every 10 s (configurable in the
options, 5–3600 s), so changes made on the device, such as a boost started with the button, show
up within seconds. While Home Assistant is connected, the EcoTimer app cannot connect. Each
thermostat uses one connection slot of the proxy (ESPHome default: 3).

## Installation

### HACS (recommended)

1. Open **HACS** in Home Assistant.
2. Menu **⋮ → Custom repositories**.
3. Repository: `https://github.com/dominguez-posh/ha-devicontrol`, type **Integration** → **Add**.
4. Search for **Kermi EcoTimer** in HACS → **Download**.
5. Restart Home Assistant (**Settings → System → Restart**).
6. EcoTimers in range of a connectable adapter or proxy show up under **Settings → Devices &
   services → Discovered** → **Add**. Alternatively **Add integration → Kermi EcoTimer** lists
   all EcoTimers Home Assistant currently sees.
7. Optional: **⚙ (options)** of each entry to set the rated power (W) and the polling interval.

Updates are offered by HACS like for any other integration.

### Manual

Copy `custom_components/kermi_ecotimer` into the `custom_components` folder of your Home
Assistant configuration and restart. Then continue with step 6 above.

### Blueprint

**Settings → Automations & scenes → Blueprints → Import blueprint** with
`https://github.com/dominguez-posh/ha-devicontrol/blob/main/blueprints/automation/kermi_ecotimer/heating_too_long.yaml`.

## Entities

| Entity | Notes |
|---|---|
| Climate | *Heat/Off*, presets *Comfort*, *Eco*, *Week program*, *Boost*. Comfort temperature is set with the dial on the device; *Off* means antifreeze (7 °C). |
| Switch *Boost* | Starts/stops a boost. |
| Number *Boost duration* | 15–240 min. The device always runs a fixed 60 min boost (no other duration is accepted, tested on firmware 2.12); Home Assistant restarts it when it runs out early and stops it at the wanted end. Also applies to boosts started with the button. |
| Option *Dial sets the boost duration when off* | While the mode is off, the dial is a boost timer: snowflake ends the boost, step 1 = 1 h … step 5 = 5 h, continuous in between (max. 5 h). Turning the dial during a boost changes the remaining time. |
| Number *Eco offset* | 2–20 °C below comfort temperature (written to the device). |
| Number *Temperature offset* | −5…+5 °C calibration of the measured temperature, stored in Home Assistant only. |
| Sensors | Temperature, comfort temperature (dial), dial position, boost remaining, phase, Bluetooth adapter, RSSI (disabled). |
| Binary sensors | Heating (relay), window open, temperature limit. |
| Power / Energy | Rated power (option, W) while the relay is on, and the accumulated energy in kWh for the energy dashboard. Measured on our devices: 800 W. |

The device clock is checked hourly and set from Home Assistant when it drifts more than 2 min.

### Rename

```yaml
action: kermi_ecotimer.rename
target:
  entity_id: climate.bad_klein_handtuchtrockner
data:
  name: Bad Klein Handtuchtrockner   # Home Assistant device name
  device_name: Bad Klein WKS         # Bluetooth name on the thermostat, max. 15 bytes
```

### Blueprint: heating too long

`blueprints/automation/kermi_ecotimer/heating_too_long.yaml` notifies the selected phones when the
*Heating* sensor has been on longer than a configurable time and optionally runs an extra action.
Import it in Home Assistant from the GitHub URL of that file.

### Week program

```yaml
action: kermi_ecotimer.set_program
target:
  entity_id: climate.thermostat_wks
data:
  days: [mon, tue, wed, thu, fri]
  base_mode: eco
  periods:
    - {start: "06:00", end: "08:30", mode: comfort}
    - {start: "18:00", end: "22:00", mode: comfort}
```

The program is stored in Home Assistant and restored by the *Week program* preset.

## Protocol

See [`custom_components/kermi_ecotimer/protocol.py`](custom_components/kermi_ecotimer/protocol.py).
`tools/` contains the scripts used for reverse engineering (bleak, run on a PC).
