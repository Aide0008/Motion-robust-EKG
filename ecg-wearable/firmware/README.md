# Firmware (Arduino IDE, ESP32 core 2.x or 3.x)

| Folder | What it is | Status |
|---|---|---|
| `mux_auto_usb/` | One AD8232 through a 16-channel multiplexer; switches electrode on leads-off, drift, rail hits, and rising noise. USB serial at 115200. | Used on hardware (first layout, ECG on pin 4, **USB only**). |
| `mux_ble/` | Same logic with all pins on the left side, the modules powered from a GPIO pin, and the same text lines also sent over Bluetooth (BLE). | Syntax-checked; compiled and run status: _confirm before publishing_. |
| `two_board_ble/` | Two AD8232 boards read simultaneously (no mux). 250 Hz, 4× oversampled, USB at 460800 and BLE. | Used on hardware for the Nov 17 recording; _state whether over USB or BLE_. |

Wiring tables: [`../docs/HARDWARE.md`](../docs/HARDWARE.md).

**Output format** (text, one line per sample)
- `mux_*`: `time_ms,pin_mV,LO+,LO-,mux_channel` and, on a switch, `S,switch_ms,bad_stretch_start_ms`
- `two_board_ble`: `time_ms,pin_mV_A,LO+_A,LO-_A,pin_mV_B,LO+_B`

If the Arduino IDE says "Sketch too big" with Bluetooth, choose Tools → Partition Scheme → "Huge APP".
