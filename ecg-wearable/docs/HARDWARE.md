# Hardware notes

## Parts
- ESP32 dev board, 30-pin (DOIT-style), Arduino core 2.x or 3.x
- 1-2 × AD8232 single-lead ECG modules (gain ≈ 1100 on the module, output centred at half the supply voltage)
- CD74HC4067 16-channel analog multiplexer (only for the single-amplifier variant)
- Disposable gel electrodes, 3-lead cable per board
- Breadboard and jumpers (note the interference lessons below)

## ESP32 pin facts that shaped the design
- **ADC1** pins (32, 33, 34, 35, 36, 39) keep working when WiFi or Bluetooth is on. **ADC2** pins (0, 2, 4, 12-15, 25-27) stop returning analog readings when the radio is on. They are still fine for plain digital I/O (leads-off inputs, mux select lines, a power pin).
- 34, 35, 36, 39 are input-only. GPIO12 is a boot-strapping pin; leave it unconnected.
- Default I2C pins (21, 22) collided with the mux select lines in the first layout.

## Wiring by firmware version

| Signal | `mux_auto_usb` (first layout) | `mux_ble` (left-side layout) | `two_board_ble` |
|---|---|---|---|
| Mux S0 / S1 / S2 / S3 | 2 / 21 / 22 / 23 | 14 / 25 / 27 / 26 | - (no mux) |
| AD8232 A output | 4 (ADC2 - **USB only**) | 33 | 33 |
| AD8232 A LO+ / LO− | 18 / 19 | 34 / 35 | 34 / 35 |
| AD8232 B output / LO+ | - | - | 32 / 26 |
| 3.3 V for the modules | 3V3 pin | pin 32 driven HIGH | pin 25 driven HIGH |

Electrodes for `two_board_ble`: board A RA = electrode 1, board B RA = electrode 2, **LA and RL shared** (see lessons - this made the boards fail together).

## Lessons learned
1. **Powering the modules from a GPIO** works (the modules draw ≈ 0.2 mA) and freed the right-hand pins, but it is a dirtier supply than the board's regulated 3V3 pin. The amplifier output sits at half its supply, so supply noise appears directly in the signal. A 3.3 V regulator or a 10 µF + 0.1 µF capacitor pair near the module is the better design.
2. **Shared electrodes defeat redundancy.** Two amplifiers sharing LA and RL see the same disturbance (correlation 0.96 while standing). Give each its own LA, at least.
3. **Mains hum scales with electrode impedance mismatch** (MATH.md section 8). Reused gel electrodes cost far more signal quality than expected.
4. **The ADC limits** (≈ 0.14 V and ≈ 3.1 V at the pin) clip a big disturbance; clipped data cannot be recovered in software. The page flags and skips such stretches.
5. **Sampling at 250 Hz with no anti-alias filter** may fold higher-frequency interference into the band (unconfirmed).
6. **Bluetooth throughput:** text lines (~24 bytes at 250 Hz = 6 kB/s) are queued and sent in 20 ms bursts of up to 3 notifications of (MTU − 3) bytes; a 24 kB ring buffer keeps ≈ 4 s through a dropout.
