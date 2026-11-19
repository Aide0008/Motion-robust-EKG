"""
make_synthetic.py - make a small, fully synthetic two-board recording in the same CSV format the web page records.

Nothing here comes from a real person: the heartbeat is a sum of Gaussian bumps (P, Q, R, S, T), board B sees a
smaller copy of it, and board A gets a burst of muscle-like noise. Because the clean signal is known, the denoiser
can be scored exactly (see demo_denoise.py). Fixed random seed -> the same file every time.

usage:  python make_synthetic.py [--seconds 30] [--out ../data/synthetic_two_board.csv]
"""
import argparse
import numpy as np

FS = 250


def clean_ecg(t, rr=0.9):
    """One 'textbook' beat repeated every rr seconds: P, Q, R, S, T as Gaussian bumps (mV)."""
    def g(d, mu, s, a):
        return a * np.exp(-0.5 * ((d - mu) / s) ** 2)
    v = np.zeros_like(t)
    k0 = np.round(t / rr)
    for k in (k0 - 1, k0, k0 + 1):                       # a beat can only affect times near it
        d = t - k * rr
        v += g(d, -0.20, 0.025, 0.12) + g(d, 0.0, 0.012, 1.0) + g(d, 0.04, 0.012, -0.22) + g(d, 0.27, 0.045, 0.30)
    return v


def muscle_noise(n, rng, rms_mv, lo=20.0, hi=100.0):
    """Band-limited noise (lo..hi Hz), a crude stand-in for muscle (EMG) activity."""
    w = rng.standard_normal(n)
    F = np.fft.rfft(w)
    f = np.fft.rfftfreq(n, 1 / FS)
    F[(f < lo) | (f > hi)] = 0
    x = np.fft.irfft(F, n)
    return x * rms_mv / x.std()


def make(seconds=30, seed=1):
    rng = np.random.default_rng(seed)
    n = seconds * FS
    t = np.arange(n) / FS
    truth = clean_ecg(t)
    baseline = 0.15 * np.sin(2 * np.pi * 0.25 * t)                     # slow breathing drift
    burst = ((t > 10) & (t < 20)).astype(float)                        # muscle burst on board A
    A = 0.8 * truth + baseline + 0.01 * rng.standard_normal(n) + burst * muscle_noise(n, rng, 0.10)
    B = 0.4 * truth + baseline + 0.01 * rng.standard_normal(n)
    return t, truth, A, B


def to_pin_mv(v_mv, gain=1100, center=1650):
    """electrode mV -> what the ESP32 reads at the amplifier output (mV), like the real hardware"""
    return np.clip(np.round(center + gain * v_mv), 150, 3100)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--out", default="../data/synthetic_two_board.csv")
    args = ap.parse_args()
    t, truth, A, B = make(args.seconds)
    a, b = to_pin_mv(A), to_pin_mv(B)
    with open(args.out, "w") as f:
        f.write("# SYNTHETIC two-board recording made by analysis/make_synthetic.py (no real person's data)\n")
        f.write("# gain 1100, 250 Hz. Board A has a muscle-noise burst from 10 s to 20 s; board B is clean but sees a smaller beat.\n")
        f.write("time_ms,mv_a,lo_plus_a,lo_minus_a,mux_ch_a,mv_b,lo_plus_b,lo_minus_b,mux_ch_b\n")
        for i in range(len(t)):
            f.write(f"{100000 + i * 4},{int(a[i])},0,0,,{int(b[i])},0,0,\n")
    print("wrote", args.out, len(t), "rows")
