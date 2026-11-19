"""
ecgdn.py - reference (Python) implementation of the ECG denoiser used in web/ecg_monitor.html.

The web page contains the same algorithm in JavaScript (the block between the markers
"DENOISER START" and "DENOISER END"). This file is written to mirror that code step by step,
so you can read the math in docs/MATH.md, run it here, and check it against the JavaScript
(analysis/tests/test_ecgdn.py does exactly that).

Pipeline for one unbroken stretch of signal x (millivolts at the electrode, sampled at FS = 250 Hz):

    1. noise_meter(x)   -> sigma[k]  : how noisy is the signal around sample k
    2. qrs_mask(x)      -> mask[k]   : is sample k inside a QRS complex
    3. kalman_rts(x, R, Q)           : smooth with a Kalman filter + Rauch-Tung-Striebel smoother,
                                       R from step 1 (measurement noise), Q from step 2 (how fast the
                                       true signal is allowed to change)

Only numpy and scipy are used.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

FS = 250.0                      # samples per second (the firmware samples every 4 ms)
SQ = np.sqrt(0.5)               # Q = 1/sqrt(2) -> Butterworth (maximally flat) 2nd-order sections

# Tuned on real muscle noise (see docs/RESULTS.md).
#   ql  : how fast the true signal may change outside a QRS      [mV^2 / s^3]
#   qh  : the same inside a QRS (much larger: the R wave is sharp)
#   rho : how much to trust the noise meter (bigger = smoother)
#   kap : QRS detector threshold (energy must be this many times its own 3 s median)
#   dil : the QRS mask is widened by this many seconds on each side
PARAMS = dict(ql=300.0, qh=8e4, rho=1.5, kap=2.0, dil=0.07)


# --------------------------------------------------------------------------------------
# 1. Filters
# --------------------------------------------------------------------------------------
def design(kind: str, f0: float, fs: float = FS):
    """Second-order Butterworth biquad (RBJ 'audio EQ cookbook' form).

    Returns (b, a) with a[0] == 1, so  y[n] = b0 x[n] + b1 x[n-1] + b2 x[n-2] - a1 y[n-1] - a2 y[n-2].
    """
    w = 2 * np.pi * f0 / fs
    c, al = np.cos(w), np.sin(w) / (2 * SQ)
    a0 = 1 + al
    if kind == "hp":
        b = np.array([(1 + c) / 2, -(1 + c), (1 + c) / 2]) / a0
    elif kind == "lp":
        b = np.array([(1 - c) / 2, (1 - c), (1 - c) / 2]) / a0
    else:
        raise ValueError(kind)
    a = np.array([1.0, -2 * c / a0, (1 - al) / a0])
    return b, a


def design_notch(f0: float, q: float = 20.0, fs: float = FS):
    """Notch (band-stop) biquad: zeros ON the unit circle at +-f0, poles just inside."""
    w = 2 * np.pi * f0 / fs
    c, al = np.cos(w), np.sin(w) / (2 * q)
    a0 = 1 + al
    b = np.array([1.0, -2 * c, 1.0]) / a0
    a = np.array([1.0, -2 * c / a0, (1 - al) / a0])
    return b, a


def _steady_state_zi(b, a, u):
    """Initial filter state so that a constant input u gives a constant output from sample 0.

    For a constant input the output is y_ss = H(z=1) * u with H(1) = sum(b) / sum(a).
    Solving the transposed direct form II state equations for that case gives
        z2 = b2*u - a2*y_ss,   z1 = b1*u - a1*y_ss + z2.
    Starting from this state removes the start-up transient ("the filter ringing at the edges").
    """
    yss = (b[0] + b[1] + b[2]) / (a[0] + a[1] + a[2]) * u
    z2 = b[2] * u - a[2] * yss
    z1 = b[1] * u - a[1] * yss + z2
    return np.array([z1, z2])


def _pass(x, ba, reverse=False):
    b, a = ba
    if reverse:
        x = x[::-1]
    y, _ = lfilter(b, a, x, zi=_steady_state_zi(b, a, x[0]))
    return y[::-1] if reverse else y


def filtfilt(x, spec):
    """Zero-phase filtering: run every section forward, then every section backward.

    The backward pass undoes the phase delay of the forward pass, so a beat stays exactly where it
    was in time. The magnitude response is squared (steeper) and nothing is "causal": the output at
    time t depends on the future, which is why the live display needs a small delay.
    spec = [('hp', 8.0), ('lp', 25.0)] etc.
    """
    y = np.asarray(x, float).copy()
    cos = [design(k, f) for k, f in spec]
    for co in cos:
        y = _pass(y, co, False)
    for co in cos:
        y = _pass(y, co, True)
    return y


def highpass_zp(x, fc):
    """Zero-phase high-pass (used for baseline removal in Review)."""
    return filtfilt(x, [("hp", fc)])


# --------------------------------------------------------------------------------------
# 2. Small running-window helpers (written to match the JavaScript exactly)
# --------------------------------------------------------------------------------------
def roll_median(a, size):
    """Centred running median; the ends repeat the first/last value. Cost O(n * size)."""
    a = np.asarray(a, float)
    n, half = len(a), size >> 1
    pad = np.concatenate([np.full(half, a[0]), a, np.full(size - 1 - half, a[-1])])
    win = np.lib.stride_tricks.sliding_window_view(pad, size)
    return np.partition(win, size >> 1, axis=1)[:, size >> 1]      # the element at sorted index size//2


def movmean(a, size):
    """Centred moving average; the ends repeat the first/last value."""
    a = np.asarray(a, float)
    h = size >> 1
    pad = np.concatenate([np.full(h, a[0]), a, np.full(h, a[-1])])
    c = np.concatenate([[0.0], np.cumsum(pad)])
    return (c[size:] - c[:-size]) / size


def dilate(mask, r):
    """Widen a 0/1 mask by r samples on each side."""
    m = np.asarray(mask, bool)
    idx = np.flatnonzero(m)
    out = np.zeros(len(m), bool)
    for i in idx:
        out[max(0, i - r): i + r + 1] = True
    return out


# --------------------------------------------------------------------------------------
# 3. Estimating the noise level and where the QRS is
# --------------------------------------------------------------------------------------
def mad_sigma(x):
    """Robust standard deviation from the median absolute value: sigma = median(|x|) / 0.6745.

    For Gaussian x, P(|x| < m) = 1/2 at m = 0.6745 sigma (the 75th percentile of the standard normal),
    so the median of |x| estimates 0.6745 sigma. Unlike the plain standard deviation it is hardly moved
    by a few large values (here: the QRS complexes).
    """
    return np.median(np.abs(x)) / 0.6745


def noise_meter(x):
    """How noisy is the signal at every sample (mV): running 1.5 s median of the >15 Hz content."""
    hp = np.abs(filtfilt(x, [("hp", 15.0)]))
    return roll_median(hp, int(round(1.5 * FS)) | 1) / 0.6745


def qrs_mask(x, kap, dil):
    """1 where a QRS complex is: 8-25 Hz energy well above its own 3 s median, widened by dil seconds."""
    y = np.abs(filtfilt(x, [("hp", 8.0), ("lp", 25.0)]))
    env = movmean(y, int(round(0.06 * FS)) | 1)
    base = roll_median(env, int(3 * FS))
    return dilate(env > kap * base, int(round(dil * FS)))


# --------------------------------------------------------------------------------------
# 4. Kalman filter + Rauch-Tung-Striebel smoother for the "integrated random walk" model
# --------------------------------------------------------------------------------------
def kalman_rts(y, R, Q):
    """Smooth y with state x = [level, slope], F = [[1, dt], [0, 1]], H = [1, 0].

    R[k] : variance of the measurement noise at sample k   (mV^2)
    Q[k] : intensity of the white noise driving the slope  (mV^2 / s^3); larger = the signal may bend faster

    Predict:  x- = F x,            P- = F P F^T + Qd,   Qd = q [[dt^3/3, dt^2/2], [dt^2/2, dt]]
    Update :  S = P-[0,0] + R,     K = P-[:,0] / S,     x = x- + K (y - x-[0]),   P = (I - K H) P-
    Smooth :  C = P F^T (P-next)^-1,     x_smooth = x + C (x_smooth_next - x-_next)    (backwards in time)

    The covariance is kept as three numbers (a = P00, b = P01, c = P11) because it is symmetric 2x2.
    Returns the smoothed level (mV).
    """
    y = np.asarray(y, float)
    n, dt = len(y), 1.0 / FS
    f0, f1 = np.zeros(n), np.zeros(n)
    P0, P1, P2 = np.zeros(n), np.zeros(n), np.zeros(n)          # filtered covariance
    p0, p1 = np.zeros(n), np.zeros(n)                           # predicted mean
    Q0, Q1, Q2 = np.zeros(n), np.zeros(n), np.zeros(n)          # predicted covariance
    x0, x1, a, b, c = y[0], 0.0, 1.0, 0.0, 10.0                 # start: level = first sample, slope unknown
    for k in range(n):
        if k > 0:
            q = Q[k]
            x0 += dt * x1
            a, b, c = (a + 2 * dt * b + dt * dt * c + q * dt ** 3 / 3,
                       b + dt * c + q * dt * dt / 2,
                       c + q * dt)
        p0[k], p1[k], Q0[k], Q1[k], Q2[k] = x0, x1, a, b, c
        S = a + R[k]
        K0, K1 = a / S, b / S
        r = y[k] - x0
        x0 += K0 * r
        x1 += K1 * r
        a, b, c = (1 - K0) * a, (1 - K0) * b, c - K1 * b
        f0[k], f1[k], P0[k], P1[k], P2[k] = x0, x1, a, b, c

    o0, o1 = f0.copy(), f1.copy()
    for k in range(n - 2, -1, -1):                              # backward (smoothing) pass
        a00, a01, a11 = P0[k], P1[k], P2[k]
        b00, b01, b11 = Q0[k + 1], Q1[k + 1], Q2[k + 1]
        det = b00 * b11 - b01 * b01
        i00, i01, i11 = b11 / det, -b01 / det, b00 / det        # inverse of the predicted covariance
        g00, g01, g10, g11 = a00 + dt * a01, a01, a01 + dt * a11, a11    # P F^T
        c00, c01 = g00 * i00 + g01 * i01, g00 * i01 + g01 * i11
        c10, c11 = g10 * i00 + g11 * i01, g10 * i01 + g11 * i11
        d0, d1 = o0[k + 1] - p0[k + 1], o1[k + 1] - p1[k + 1]
        o0[k] = f0[k] + c00 * d0 + c01 * d1
        o1[k] = f1[k] + c10 * d0 + c11 * d1
    return o0


def denoise_run(x, strength=1.0):
    """Denoise one unbroken stretch x (mV). Returns dict(out, sig, mask)."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 40:
        return dict(out=x.copy(), sig=np.zeros(n), mask=np.zeros(n, bool))
    P = PARAMS
    sig = noise_meter(x)
    mask = qrs_mask(x, P["kap"], P["dil"])
    rho = P["rho"] * (strength or 1.0)
    R = np.maximum((sig * rho) ** 2, 1e-4)
    Q = np.where(mask, P["qh"], P["ql"])
    return dict(out=kalman_rts(x, R, Q), sig=sig, mask=mask)


# --------------------------------------------------------------------------------------
# 5. Beat detection (for the heart-rate readout)
# --------------------------------------------------------------------------------------
def detect_beats(x):
    """R-peak sample indices: band-pass 6-20 Hz, slope squared, 80 ms average, adaptive threshold,
    0.28 s refractory period, then snap to the largest |value| within +-15 samples (a Pan-Tompkins-style detector)."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 2 * FS:
        return []
    y = filtfilt(x, [("hp", 6.0), ("lp", 20.0)])
    d = np.zeros(n)
    g = (y[2:] - y[:-2]) / 2
    d[1:-1] = g * g
    m = movmean(d, int(round(0.08 * FS)) | 1)
    thr = 0.3 * np.sort(m)[int(np.floor(0.95 * (n - 1)))]
    cand = [i for i in range(1, n - 1) if m[i] >= thr and m[i] > m[i - 1] and m[i] >= m[i + 1]]
    cand.sort(key=lambda i: -m[i])
    refr, acc = int(round(0.28 * FS)), []
    for c in cand:
        if all(abs(a - c) >= refr for a in acc):
            acc.append(c)
    acc.sort()
    out = []
    for c in acc:
        lo, hi = max(0, c - 15), min(n - 1, c + 15)
        out.append(lo + int(np.argmax(np.abs(y[lo:hi + 1]))))
    return out


def bpm_from_beats(beats, fs=FS, rr_min=0.3, rr_max=2.5, min_rr=3):
    """Median-RR heart rate; RR intervals outside [rr_min, rr_max] seconds are ignored."""
    rr = np.diff(np.asarray(beats, float)) / fs
    rr = rr[(rr >= rr_min) & (rr <= rr_max)]
    return None if len(rr) < min_rr else 60.0 / float(np.median(rr))
