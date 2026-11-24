# The math and algorithms, step by step

This document explains every algorithm in the project: what it does, why it is built that way, and where it lives in the
code. The Python in [`analysis/ecgdn.py`](../analysis/ecgdn.py) mirrors the JavaScript in
[`web/ecg_monitor.html`](../web/ecg_monitor.html) (a test checks they agree to 6 decimals), so you can read either.

**Notation.** `fs = 250 Hz` is the sample rate, `dt = 1/fs = 4 ms`. `x[k]` is sample number `k`. "Pin mV" means millivolts
at the amplifier output pin (what the ESP32 reads); "electrode mV" = pin mV / 1100 (the AD8232 module's gain).

Each section ends with a few **check yourself** questions. If you can answer them without looking, you understand it.

---

## 1. Sampling, the ADC and aliasing

**What happens.** The AD8232 amplifies the tiny electrode voltage (about 1 mV for an R wave) by ~1100 and centres it near half
the supply voltage (~1.65 V). The ESP32's 12-bit ADC measures that every 4 ms (`analogReadMilliVolts`). Output range is
roughly 0.14 V to 3.1 V; outside it the reading is **pinned at a limit** (the real signal is lost).

**Nyquist and aliasing.** A sampled signal cannot distinguish frequencies that differ by a multiple of `fs`. A component at
frequency `f` appears at

$$ f_\text{alias} = \left| f - \mathrm{round}\!\left(\frac{f}{f_s}\right) f_s \right| $$

so with `fs = 250 Hz` a 300 Hz tone shows up at **50 Hz**, and a 200 Hz tone also at 50 Hz. The ESP32 ADC has no anti-alias
filter, and the AD8232 module's own low-pass is only second order, so high-frequency interference (radio bursts, switching
supplies, mains harmonics) can fold into the ECG band. This is the leading *hypothesis* for the unexplained 40-55 Hz band in
[RESULTS.md](RESULTS.md); it has **not** been confirmed.

**Oversampling.** Averaging `N` readings taken at rate `f1` is a moving-average filter with magnitude response

$$ |H(f)| = \left| \frac{\sin(\pi N f / f_1)}{N \sin(\pi f / f_1)} \right| $$

which has zeros at multiples of `f1/N`. Averaging four back-to-back reads (what `ecg_two_board_v5.ino` does) mostly reduces
converter noise; it does *not* act as an anti-alias filter for 50-300 Hz because the four reads are only microseconds apart.
A real anti-alias scheme would sample at e.g. 1 kHz, low-pass digitally, then keep every 4th sample.

**Throughput.** One two-board line such as `100000,2533,0,0,2078,0\n` is about 24 bytes → `250 × 24 = 6 kB/s`. Serial at 115200
baud (8N1) carries 11.5 kB/s (52 % used, too tight), at 460800 baud 46 kB/s (13 %).

> **Check yourself:** (1) Which frequency does a 190 Hz tone appear at when sampled at 250 Hz? (2) Why can't a digital filter
> after sampling remove an aliased tone? (3) What is the time resolution of 250 Hz sampling, and what does that mean for
> measuring an RR interval?

---

## 2. Digital filters

### 2.1 The biquad

Every filter here is a second-order section ("biquad") with the difference equation

$$ y[n] = b_0 x[n] + b_1 x[n-1] + b_2 x[n-2] - a_1 y[n-1] - a_2 y[n-2]. $$

Its transfer function is $H(z) = \dfrac{b_0 + b_1 z^{-1} + b_2 z^{-2}}{1 + a_1 z^{-1} + a_2 z^{-2}}$ and its frequency response is
$H(e^{j\omega})$ with $\omega = 2\pi f / f_s$.

**Butterworth low/high-pass** (`design` in `ecgdn.py`, Robert Bristow-Johnson "audio EQ cookbook" form). With
$\omega_0 = 2\pi f_0/f_s$, $\alpha = \sin\omega_0 / (2Q)$, $Q = 1/\sqrt2$ (maximally flat magnitude), $a_0 = 1+\alpha$:

| | $b_0$ | $b_1$ | $b_2$ |
|---|---|---|---|
| low-pass | $\frac{1-\cos\omega_0}{2a_0}$ | $\frac{1-\cos\omega_0}{a_0}$ | $\frac{1-\cos\omega_0}{2a_0}$ |
| high-pass | $\frac{1+\cos\omega_0}{2a_0}$ | $-\frac{1+\cos\omega_0}{a_0}$ | $\frac{1+\cos\omega_0}{2a_0}$ |

and for both $a_1 = -2\cos\omega_0 / a_0$, $a_2 = (1-\alpha)/a_0$.

**Notch** (`design_notch`): $b = [1,\,-2\cos\omega_0,\,1]/a_0$ - the zeros sit exactly on the unit circle at $\pm\omega_0$, so the
gain at $f_0$ is exactly 0; the poles sit just inside, so the notch is narrow. Bandwidth $\approx f_0/Q$; with $Q=20$ at
60 Hz that is 3 Hz wide. Mains is 60 Hz in the US (50 Hz elsewhere).

> **Check yourself:** Show that $H(1)$ for the low-pass (DC gain, $z=1$) equals 1 and for the high-pass equals 0. Show the
> notch has $H(e^{j\omega_0}) = 0$ by putting $z = e^{j\omega_0}$ in the numerator.

### 2.2 Starting without a transient

A filter that starts with zero memory "rings" at the beginning of a record. `_steady_state_zi` initialises the memory so a
constant input $u$ produces a constant output from the first sample. In transposed direct form II the output is
$y = b_0 x + z_1$ and the state updates are $z_1' = b_1 x - a_1 y + z_2$, $z_2' = b_2 x - a_2 y$. For constant $x=u$ and $y = y_{ss}$
the states must not change, which gives

$$ y_{ss} = \frac{b_0+b_1+b_2}{1+a_1+a_2}\,u,\qquad z_2 = b_2 u - a_2 y_{ss},\qquad z_1 = b_1 u - a_1 y_{ss} + z_2 . $$

### 2.3 Zero-phase filtering (`filtfilt`)

A causal filter delays different frequencies by different amounts (phase), which smears and shifts a QRS complex. Running the
filter forward, then running the *same* filter on the time-reversed result and reversing again, gives

$$ Y(e^{j\omega}) = H(e^{j\omega})\,\overline{H(e^{j\omega})}\,X = |H(e^{j\omega})|^2 X $$

- the phase cancels (zero delay) and the magnitude is squared (twice as steep; a "−3 dB" corner becomes −6 dB). The price: the output
at time $t$ depends on the future, so it needs the whole record - fine for Review, impossible for a live display. The live
display therefore uses a *fixed lag* (section 5.5).

> **Check yourself:** Why does forward-backward filtering double the filter order in the magnitude response but not the delay?
> What goes wrong if you forward-filter the beat detector's output and then threshold it - does the peak still line up with the R wave?

---

## 3. Baseline wander

Breathing, posture and electrode movement add a slow drift. The page tracks it with a first-order exponential filter and
subtracts it:

$$ \text{base}[n] = \text{base}[n-1] + \bigl(1 - e^{-dt/\tau}\bigr)\,\bigl(x[n] - \text{base}[n-1]\bigr),\qquad v[n] = x[n] - \text{base}[n]. $$

The tracker is a low-pass with cutoff $f_c = 1/(2\pi\tau)$, so $v$ is a **high-pass** with the same cutoff:

| setting | $\tau$ | cutoff | effect |
|---|---|---|---|
| Off | 8 s | 0.02 Hz | only the DC level is removed |
| Light | 1.5 s | 0.11 Hz | the original behaviour |
| Firm (live) | 0.35 s | 0.45 Hz | flatter line, easier to see the P wave |
| Firm (Review) | 8 s tracker, then zero-phase 0.5 Hz high-pass | 0.5 Hz | flat line with **no** beat shift |

**Trade-off.** A higher cutoff gives a flatter baseline but distorts slow parts of the ECG - the ST segment and T wave live below
~1 Hz. Diagnostic ECG standards recommend a much lower cutoff (see the reading list); a monitor can use more. Distortion is why
the Review mode uses the zero-phase version.

> **Check yourself:** Derive $f_c = 1/(2\pi\tau)$ for the filter above (hint: continuous-time first-order low-pass $H(s) = 1/(1+s\tau)$).
> Why is a *causal* 0.45 Hz high-pass more harmful to the ST segment than a zero-phase 0.5 Hz one?

---

## 4. Estimating noise robustly, and finding the QRS

### 4.1 Median absolute deviation (MAD)

We want the noise level **while beats are present**. The ordinary standard deviation is dominated by the large R waves. The
median is not. For Gaussian noise with standard deviation $\sigma$, $P(|X| < m) = 1/2$ at $m = \Phi^{-1}(0.75)\,\sigma = 0.6745\,\sigma$, so

$$ \hat\sigma = \frac{\mathrm{median}(|x|)}{0.6745}. $$

(`mad_sigma`; the tests show it recovers $\sigma$ to 2 % on Gaussian data and shrugs off 1 % spikes that wreck the std.)

### 4.2 The noise meter

`noise_meter`: high-pass at 15 Hz (zero-phase), take $|\cdot|$, take a **running 1.5 s median**, divide by 0.6745. The result
$\sigma[k]$ (mV) is "how noisy is the signal around sample $k$". A QRS complex occupies about 10 % of the time and mostly
carries energy below ~40 Hz, so it hardly moves the median. Why 15 Hz? Muscle noise is broadband (tens to hundreds of Hz);
most clean ECG energy is below 15 Hz, so the >15 Hz part is mostly noise.

> **Limit.** On real recordings 45-60 % of flex noise power was *below* 5 Hz, the same band as the P and T waves. The meter
> cannot see that part, and no filter can remove it without distorting the P and T waves (see RESULTS.md).

### 4.3 The QRS mask

`qrs_mask`: band-pass 8-25 Hz (zero-phase), take $|\cdot|$, smooth over 60 ms ("envelope"), compare to $\kappa \times$ its own running 3 s
median ($\kappa = 2$), and widen the result by ±70 ms. Inside the mask the Kalman filter is allowed to change quickly (section 5);
outside it must stay smooth.

> **Check yourself:** Why use the *median* of the envelope as the reference rather than its mean? What would happen to the mask
> if the heart rate doubled?

---

## 5. Kalman filter + Rauch-Tung-Striebel smoother

This is the core denoiser (`kalman_rts`, `denoise_run`).

### 5.1 The model

We treat the clean signal as a smooth curve described by two numbers: its **level** $f$ and its **slope** $s=f'$. State
$\mathbf{x}=[f,\,s]^\top$. Between samples the level moves along the slope, and the slope itself gets pushed around by random
forces ("integrated random walk"; the slope is a random walk):

$$ \mathbf{x}_k = F\,\mathbf{x}_{k-1} + \mathbf{w}_k,\quad F=\begin{bmatrix}1 & dt\\ 0 & 1\end{bmatrix},\quad
\mathbf{w}_k\sim\mathcal N(0,Q_d),\quad Q_d = q\begin{bmatrix} dt^3/3 & dt^2/2\\ dt^2/2 & dt\end{bmatrix} $$

$$ y_k = H\mathbf{x}_k + v_k,\quad H = [1\ 0],\quad v_k\sim\mathcal N(0,R_k). $$

$q$ (mV²/s³) is the intensity of white noise driving the slope. $Q_d$ is the exact integral of the continuous model over one step. $R_k$
is the measurement-noise variance, set from the noise meter: $R_k = \max\bigl((\rho\,\sigma_k)^2,\ 10^{-4}\bigr)$ with $\rho=1.5$.

### 5.2 Filter (forward in time)

*Predict:* $\hat{\mathbf x}^-_k = F\hat{\mathbf x}_{k-1}$, $\;P^-_k = F P_{k-1} F^\top + Q_d$.

*Update:* $S = P^-_{00} + R_k$, $\;K = P^-_{:,0}/S$, $\;\hat{\mathbf x}_k = \hat{\mathbf x}^-_k + K\,(y_k - \hat x^-_{k,0})$, $\;P_k = (I-KH)P^-_k$.

$K$ is the minimum-mean-square-error gain: when $R_k$ is large (noisy), $K$ is small and the estimate barely moves toward the
measurement; when $R_k$ is small, it follows the measurement. Because $P$ is symmetric 2×2 the code stores three numbers
$a=P_{00},\,b=P_{01},\,c=P_{11}$, giving $a^- = a+2\,dt\,b+dt^2 c+q\,dt^3/3$, $b^-=b+dt\,c+q\,dt^2/2$, $c^-=c+q\,dt$.

### 5.3 Smoother (backward in time)

The filter at time $k$ only knows the past. After the whole record is in hand the RTS smoother revisits every sample using the
future too:

$$ C_k = P_k F^\top (P^-_{k+1})^{-1},\qquad \hat{\mathbf x}^s_k = \hat{\mathbf x}_k + C_k\bigl(\hat{\mathbf x}^s_{k+1} - \hat{\mathbf x}^-_{k+1}\bigr). $$

Only the mean is smoothed (the covariance is not needed for the output). The final trace is $\hat x^s_{k,0}$.

### 5.4 Why this is a good denoiser: the spline connection and the bandwidth

With constant $q$ and $R$, the smoothed level is the **cubic smoothing spline**: the curve $f$ minimising

$$ \sum_k \frac{(y_k - f_k)^2}{R} + \frac{1}{q}\int f''(t)^2\,dt . $$

The first term says "stay near the data" (weighted by how much you trust it); the second says "don't bend" (weighted by how much
bending you expect). Raising $q$ allows more bending; raising $R$ trusts the data less. The effective low-pass bandwidth scales as
$(q/r)^{1/4}$ with $r = R\,dt$ the noise per unit time. Measured on this exact smoother (`analysis` check, steady state):

$$ f_{-3\,\mathrm{dB}} \approx 0.8\;\frac{(q/r)^{1/4}}{2\pi} . $$

| $q$ | $\rho\sigma$ | measured −3 dB | formula |
|---|---|---|---|
| 300 | 0.03 mV (rest) | 12.2 Hz | 12.2 Hz |
| 300 | 0.15 mV (flex) | 5.4 Hz | 5.4 Hz |
| 8·10⁴ | 0.15 mV (flex, *inside* QRS) | 22 Hz | 22 Hz |

(The table's formula column uses the 0.8 factor; without it the formula overestimates by 25 %.) This is the heart of the design:
**when noise is low the filter is wide (keeps the P/T detail), when noise is high it narrows, and inside the QRS it widens again
so the sharp R wave is kept.** With a fixed-bandwidth filter you must pick one compromise.

### 5.5 Live use: fixed-lag smoothing

The smoother needs the future. For the live display every 25 samples (0.1 s) the page re-smooths the last 8 s and "finalises"
samples that are at least 0.5 s old. The display therefore lags by $\ge 0.62$ s but each shown sample has had 0.5 s of
future to learn from. A longer lag buys accuracy; 0.5 s is long relative to the filter's memory at these $q$ values.

### 5.6 Choosing the numbers

$q_l=300$, $q_h=8\cdot10^4$, $\rho=1.5$, $\kappa=2$ were tuned on real flex noise so the R-wave height stays ≥ 95 % while SNR
improves (see RESULTS.md). Tuning against a single subject is a limitation, not a result.

> **Check yourself:** (1) What happens to the filtered curve as $q\to\infty$? As $R\to\infty$? (2) Verify $Q_d$ by integrating
> $\int_0^{dt} \Phi(\tau)\,\begin{bmatrix}0&0\\0&q\end{bmatrix}\Phi(\tau)^\top d\tau$ with $\Phi(\tau)=\begin{bmatrix}1&\tau\\0&1\end{bmatrix}$ (hint: you get the matrix above with
> $dt^3/3$ in the corner). (3) The test `test_kalman_reproduces_a_noiseless_ramp` allows a larger error in the first samples - why?

---

## 6. Beat detection and heart rate

`detect_beats` follows the structure of the classic Pan-Tompkins detector (1985):

1. band-pass 6-20 Hz (zero-phase) - isolates QRS energy;
2. derivative $g = (y_{i+1}-y_{i-1})/2$, then square it - emphasises steep slopes;
3. moving average of 80 ms;
4. threshold $= 0.3 \times$ the 95th percentile of this signal (adapts to amplitude);
5. local maxima above the threshold, strongest first, rejecting any within the 0.28 s refractory period of an accepted peak;
6. snap each peak to the largest $|y|$ within ±15 samples (60 ms).

**BPM** (`bpm_from_beats`): the median of RR intervals; intervals outside 0.3-2.5 s are ignored (they span gaps or false peaks);
at least 3 intervals are required, else "--". The median is used for the same reason as in section 4: one missed or extra beat
barely moves it.

**Resolution.** At 250 Hz one sample is 4 ms; at 60 bpm an RR of 1.000 s is known to about ±0.4 %. Beat-to-beat variability measures
(HRV) need good timing, which is another reason to avoid causal filters that shift the R wave.

**Limit.** A detector tuned on clean data can report a plausible BPM from noise. When the real beats are invisible (the standing
test) the readout cannot be trusted; a signal-quality gate is future work.

> **Check yourself:** Why square the derivative? Why a refractory period of 0.28 s, and what heart rate would exceed it? What does
> the median-RR BPM do with one missed beat compared with a mean-RR BPM?

---

## 7. Channel quality and switching

### 7.1 A running median without storing samples

For the noise measure the firmware/page keeps a **multiplicative median tracker** of $d = |v_n - v_{n-1}|$:

$$ m \leftarrow m\,(1+r) \ \text{if}\ d>m,\qquad m \leftarrow m\,(1-r)\ \text{otherwise},\qquad r = 0.006. $$

In steady state $E[\ln m]$ stops changing when $P(d>m) = P(d<m)$, i.e. $m$ is the **median** of $d$ - without storing a window of data. A
factor-of-2 change is tracked in $\ln 2 / r \approx 115$ samples ≈ 0.5 s.

### 7.2 Quality score and the decision (two boards, in the page)

$\text{quality} = \dfrac{\text{noise}}{\text{amp}}$ where amp is a decaying peak of $|v|$ (4 s time constant). A noisy board with a big beat can still beat a quiet
board with a tiny beat. The page switches to the other board only if

- it has been at least **4 s** since the last switch **and** the other board's quality number is less than **0.6×** the current one (hysteresis); or
- the current board is leads-off, or stuck at a limit.

**Limit detection.** A share of samples at a limit, $\text{satFrac} \leftarrow \text{satFrac} + (\text{hit} - \text{satFrac})/(0.5 f_s)$ (an exponential average over ~0.5 s), flags a board "bad" above 0.2; a run of
≥ 25 consecutive limit samples (0.1 s) marks the signal *dead* and the samples are ignored (a short clipped peak is processed normally).

**A bug worth remembering.** The first version flagged "bad" per *sample*. When an interference tone swung both boards in and out of
the limits, "bad" flipped every few samples and the display switched boards 118 times in 48 s (and each switch opened a settling gap that
blanked the line). Averaging over 0.5 s and requiring a minimum dwell time fixed it (8 switches). Lesson: decisions made on a noisy
indicator need smoothing and hysteresis.

### 7.3 The multiplexer firmware (`mux_ble`, `mux_auto_usb`)

One amplifier, one electrode at a time: the firmware switches electrode when it sees (a) leads-off, (b) the signal far from its baseline for 150 ms, (c) a rail hit, or (d) the noise tracker 2× above that electrode's own learned reference for 1 s. Each switch costs ≈ 2.5 s of
settling and the idle electrode's noise is unknown - which is why the two-amplifier design reads both at once.

> **Check yourself:** Why divide noise by amplitude? Give a case where it chooses the wrong board. Why must the switch rule have a
> minimum dwell time?

---

## 8. Interference: where hum and "walking noise" come from

**Mains hum.** Displacement current $i_d$ flows from mains wiring through the air into the body and out through the electrodes. A first-order model: the
voltage at each input is $i_d \cdot Z_e$ ($Z_e$ = that electrode's skin impedance). The amplifier subtracts RA from LA, so the *difference* is
about $i_d\,\Delta Z_e$: **hum grows with the mismatch between the electrodes' impedances.** Dried-out or reused gel electrodes have both
higher and less equal impedance. The AD8232's right-leg drive (RLD) feeds back an inverted common-mode signal to reduce the common part, but it cannot fix a mismatch.

**Motion.** Moving changes the skin-electrode interface (a battery-like half-cell potential across the gel that shifts when the contact is disturbed) and cable
capacitance. Slow shifts look like baseline wander; fast ones look like bursts.

**Muscle (EMG).** Broadband noise from nearby muscle contraction - the flex test - that overlaps the ECG band (section 4.2).

**Redundancy needs independence.** Two boards sharing LA and RL showed a 0.96 correlation in the 36-46 s standing window: a disturbance at a shared electrode hits both
boards identically, so switching between them cannot help. True redundancy needs independent electrodes for every input.

> **Check yourself:** Estimate the hum for $i_d=10$ nA and $\Delta Z_e = 20$ kΩ versus 200 kΩ. What does that say about
> reusing electrodes?

---

## 9. What has *not* been validated

- All real data are from one person, mostly lying down, in one place.
- Denoiser parameters were tuned on that data; improvements on **synthetic** data (+13 dB) are far larger than on real flex noise (≈ +2.5 dB) because real muscle noise overlaps the P/T band.
- No comparison against a reference ECG device or an annotated database (e.g. PhysioNet's MIT-BIH Arrhythmia and Noise Stress Test databases) has been done yet.
- Not a medical device; no claim about diagnosing anything.
