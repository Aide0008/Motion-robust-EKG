# Results, including what did not work

Everything below is from **one person (the author), one setup, mostly lying down**. There is no ground-truth reference
recording, so "SNR" figures on real data are relative to a filtered estimate, not to a certified device. Treat these as
engineering notes from a prototype, not as validation.

## 1. Single amplifier + electrode multiplexer (Nov 15 recording, 4.5 min, electrode C0 then C1)

| Finding | Number |
|---|---|
| Electrode C0 at rest | clean ECG, negative-going QRS about −0.8 to −0.9 mV, ≈ 60 bpm |
| Electrode C1 at rest | weak: R wave about 0.3-0.5 mV |
| Noise meter at rest vs flexing the pectoral muscles | 0.017 mV vs 0.09-0.12 mV (5-7×) |
| Share of flex-noise power at 0.5-5 Hz (the P/T band) | 45-60 % |
| Ideal linear (Wiener) filter, best possible SNR gain | ≈ +4 dB, but it flattens R waves to 62-83 % of their height |
| Original Kalman setting | ≈ +2 dB |
| Retuned Kalman (ql 300, qh 8·10⁴, ρ 1.5, κ 2) | ≈ +2.5 dB, R-wave height ≥ 95 % |
| Beat detector on the *raw* signal | 96-100 % of beats right |

**Why the first auto-switch rule never fired.** It reacted to excursions of ~700 mV at the pin; flex noise only swung ±350 mV, so it never
switched even though the trace was clearly worse. The fix was a noise-level trigger (running median of the sample-to-sample step, compared with that
electrode's own learned reference). In simulation built from the recorded noise: no false switches at rest (110 s and 10 min), one switch ≈ 2.6 s after flex began on the
active electrode, none when the *idle* electrode was flexed, and the expected switch-back behaviour. Not yet tested on hardware over a long walk.

**Takeaway.** The denoiser's real-world gain is modest because muscle noise overlaps the P/T wave band. The synthetic demo (`analysis/demo_denoise.py`) shows +13 dB
only because the synthetic noise is idealised band-limited noise at 20-100 Hz - **do not quote the synthetic number as a result**.

## 2. Two amplifier boards at the same time (Nov 17 recording, 48 s, lying → tap → standing)

| Quantity (pin mV, Board A unless stated) | Nov 15, rest (40 s window) | Nov 17, rest (first 10 s) |
|---|---|---|
| 60 Hz hum amplitude | 13 | 251 (B: 288) |
| 40-125 Hz noise (RMS) | 24 | 246 (B: 280) |
| Typical sample-to-sample step (median) | 19 | 237 (B: 273) |

Nov 17 was about **10-20× noisier at rest** than Nov 15, depending on the measure. What changed between the two setups: the 3.3 V supply came from a GPIO pin instead of the regulated 3V3 pin,
a new breadboard layout with more loose wire, reused gel electrodes, and two boards sharing the LA and RL electrodes. The cause has not been isolated yet (see "Next steps").

| While standing (36-46 s) | |
|---|---|
| RMS of each board | 879 and 895 pin mV |
| Correlation between boards A and B | 0.96 (0.69 at rest) |
| RMS of A − B | 250 pin mV (28 % of A's RMS) |
| 40-55 Hz band RMS, Board A | ≈ 940 pin mV (≈ 50 at rest) |
| Share of samples at an amplifier limit | 17-19 % in the 1 s windows around 38 s and 42 s |

- **Both boards failed together.** Their shared LA/RL electrodes carry the same disturbance into both amplifiers, so "switch to the other board" cannot help.
- **The signal was pinned at the amplifier limits** (≈ 0.14 V and ≈ 3.1 V at the pin) for stretches of 2-3 s, so there is nothing to recover from those parts.
- A tone-like hump around 45-50 Hz appears while standing. 45-50 Hz is not mains or physiology in the US; one candidate is higher-frequency interference aliased by the 250 Hz sampling
  (a 300 Hz component appears at 50 Hz). **Unconfirmed** - the test is to sample faster and see whether the hump stays at 45-50 Hz.
- **Software fix and its limit.** The page now ignores stretches pinned at a limit instead of filtering them as real data, and its auto-select takes them into account. That removed spurious
  switching (118 board switches → 8 on the same file) but the denoised trace while standing still shows no visible beats: the heartbeat is buried. Only hardware changes can fix that.

## 3. Next steps that would turn this into evidence

1. Isolate the noise: one change at a time (real 3V3 supply, fresh electrodes, separate LA per board, battery power), 10 s at rest each, same metrics as above.
2. Anti-alias: sample at ≥ 1 kHz, decimate digitally to 250 Hz; see if the 45-50 Hz band changes.
3. Validate on public data with labels: PhysioNet MIT-BIH Arrhythmia Database with the Noise Stress Test Database; report beat-detection sensitivity and positive predictive value
   (AAMI EC57 style) and SNR improvement against standard baselines (band-pass, wavelet) at several noise levels.
4. Walking test with an accelerometer to use motion as a noise reference.
5. Compare against a reference recording (e.g. a consumer single-lead device) on the same person.
