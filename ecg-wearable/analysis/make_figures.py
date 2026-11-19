"""
make_figures.py - regenerate every figure used in the README (images/*.png).

    python make_figures.py                      # figures that need no real data (synthetic / computed)
    python make_figures.py --real DIR           # also the two figures made from a real recording export
                                                # (DIR = a folder written by export_for_matlab.py)

Colours: a validated categorical palette (blue, orange, aqua); every line is labelled directly because aqua is low-contrast.
"""
import argparse
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from scipy.signal import lfilter, welch

import ecgdn as dn
import make_synthetic as syn

OUT = Path(__file__).resolve().parent.parent / "images"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e4de", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10.5, "axes.edgecolor": INK2, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.facecolor": SURF, "figure.facecolor": SURF,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
                     "grid.linewidth": 0.8, "axes.axisbelow": True, "lines.linewidth": 1.7})
FS = dn.FS


def save(fig, name):
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, dpi=130, bbox_inches="tight", facecolor=SURF)
    plt.close(fig)
    print("wrote", OUT / name)


def box(ax, x, y, w, h, text, fc="#ffffff", ec=INK2, size=9.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=fc, ec=ec, lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color=INK, fontweight="bold" if bold else "normal")


def arrow(ax, x0, y0, x1, y1, label=None, dy=0.12):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=13, color=INK2, lw=1.3))
    if label:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2 + dy, label, ha="center", fontsize=8.5, color=INK2)


# ---- Figure 1: the system -------------------------------------------------------------------------------
def fig_system():
    fig, ax = plt.subplots(figsize=(11, 3.6)); ax.axis("off"); ax.set_xlim(0, 11); ax.set_ylim(0, 3.6)
    ax.grid(False)
    box(ax, 0.1, 1.9, 1.5, 0.8, "Electrode 1\n(RA, board A)", "#e8f0fb"); box(ax, 0.1, 0.8, 1.5, 0.8, "Electrode 2\n(RA, board B)", "#fdece5")
    box(ax, 2.2, 1.9, 1.5, 0.8, "AD8232\nboard A", "#ffffff", bold=True); box(ax, 2.2, 0.8, 1.5, 0.8, "AD8232\nboard B", "#ffffff", bold=True)
    box(ax, 4.4, 1.0, 1.9, 1.6, "ESP32\n250 samples/s\n4x oversampled", "#ffffff", bold=True)
    box(ax, 7.0, 1.0, 1.5, 1.6, "USB serial\nor\nBluetooth LE", "#ffffff")
    box(ax, 9.1, 0.55, 1.8, 2.5, "Web page\nfilters, baseline,\nKalman + RTS,\nbeats / BPM,\nrecord, review", "#ffffff", bold=True)
    for y in (2.3, 1.2):
        arrow(ax, 1.6, y, 2.2, y); arrow(ax, 3.7, y, 4.4, 2.2 if y > 2 else 1.4)
    arrow(ax, 6.3, 1.8, 7.0, 1.8); arrow(ax, 8.5, 1.8, 9.1, 1.8)
    ax.text(5.35, 0.35, "LA and RL electrodes (shared); 3.3 V and GND from the ESP32", ha="center", fontsize=8.5, color=INK2)
    ax.text(5.5, 3.35, "Figure 1: Signal path from skin to screen", ha="center", fontsize=11, color=INK, fontweight="bold")
    save(fig, "fig1_system.png")


# ---- Figure 2: aliasing --------------------------------------------------------------------------------------
def fig_aliasing():
    n = 2000; t = np.arange(n) / FS
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    x = np.sin(2 * np.pi * 300.0 * t); w = np.hanning(n)
    F = np.abs(np.fft.rfft(x * w)) / (w.sum() / 2); f = np.fft.rfftfreq(n, 1 / FS)
    ax.plot(f, F, color=ORANGE, lw=1.8)
    ax.annotate("a 300 Hz tone appears here, at 50 Hz\n(a real 50 Hz signal would look identical)", (50, 1.0), xytext=(58, 0.78), color=INK, fontsize=9.5,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.axvline(FS / 2, color=INK2, ls=":", lw=1); ax.text(FS / 2 - 1, 1.04, "Nyquist (125 Hz)", ha="right", fontsize=8.5, color=INK2)
    ax.set_xlim(0, 125); ax.set_ylim(0, 1.15); ax.set_xlabel("frequency seen after sampling at 250 Hz (Hz)"); ax.set_ylabel("amplitude")
    ax.set_title("Figure 2: A 300 Hz tone folds down to 50 Hz when sampled at 250 Hz", loc="left", fontsize=11, color=INK, fontweight="bold")
    save(fig, "fig2_aliasing.png")


# ---- Figure 3: zero-phase vs one pass --------------------------------------------------------------------------
def fig_zero_phase():
    t = np.arange(0, 1.0, 1 / FS)
    x = syn.clean_ecg(t - 0.5, rr=2.0)                      # one beat, R wave at 0.5 s
    b, a = dn.design("lp", 20.0)
    one = lfilter(b, a, x); zp = dn.filtfilt(x, [("lp", 20.0)])
    fig, ax = plt.subplots(figsize=(7.5, 3.3))
    ax.plot(t, x, color=INK2, lw=1.1); ax.plot(t, one, color=ORANGE); ax.plot(t, zp, color=BLUE)
    pk = lambda y: t[np.argmax(y)]
    ax.set_xlim(0.2, 0.9); ax.set_ylim(-0.35, 1.15); ax.set_xlabel("time (s)"); ax.set_ylabel("mV")
    ax.annotate(f"original: R peak at {pk(x):.3f} s", (pk(x), x.max()), xytext=(0.22, 1.02), color=INK, fontsize=9, arrowprops=dict(arrowstyle="-", color=INK2, lw=.8))
    ax.annotate(f"one pass: peak at {pk(one):.3f} s (late)", (pk(one), one.max()), xytext=(0.60, 0.92), color=ORANGE, fontsize=9, arrowprops=dict(arrowstyle="-", color=ORANGE, lw=.8))
    ax.annotate(f"forward + backward: {pk(zp):.3f} s (on time)", (pk(zp) + 0.004, zp.max() * 0.9), xytext=(0.60, 0.74), color=BLUE, fontsize=9, arrowprops=dict(arrowstyle="-", color=BLUE, lw=.8))
    ax.set_title("Figure 3: Zero-phase filtering keeps the R wave at the right time", loc="left", fontsize=11, color=INK, fontweight="bold")
    save(fig, "fig3_zero_phase.png")


# ---- Figure 4: the smoother's bandwidth adapts ----------------------------------------------------------------------
def fig_bandwidth():
    n = 5000; t = np.arange(n) / FS; fr = np.geomspace(0.5, 60, 36)
    cases = [("quiet (noise 0.03 mV), between beats", 300.0, 0.03, BLUE), ("muscle noise (0.15 mV), between beats", 300.0, 0.15, ORANGE),
             ("muscle noise (0.15 mV), inside the QRS", 8e4, 0.15, AQUA)]
    fig, ax = plt.subplots(figsize=(7.8, 3.9))
    for lab, q, s, col in cases:
        g = []
        for f in fr:
            x = np.sin(2 * np.pi * f * t); o = dn.kalman_rts(x, np.full(n, s * s), np.full(n, q))
            sl = slice(1700, 3300); g.append(np.sqrt(np.mean(o[sl] ** 2)) / np.sqrt(np.mean(x[sl] ** 2)))
        g = np.array(g); i = np.argmax(g < 0.7071)
        ax.plot(fr, g, color=col, label=f"{lab}: -3 dB at ~{fr[i]:.0f} Hz"); ax.plot(fr[i], g[i], "o", color=col, ms=5)
    ax.axhline(0.7071, color=INK2, ls=":", lw=1)
    ax.set_xscale("log"); ax.set_xlim(0.5, 60); ax.set_ylim(0, 1.08); ax.set_xlabel("signal frequency (Hz)"); ax.set_ylabel("how much of it passes (gain)")
    ax.legend(frameon=False, fontsize=8.8, loc="lower left")
    ax.set_title("Figure 4: The smoother narrows when noise rises and opens inside a QRS", loc="left", fontsize=11, color=INK, fontweight="bold")
    save(fig, "fig4_bandwidth.png")


# ---- Figure 6: choosing a board -----------------------------------------------------------------------------------------
def fig_switching():
    fig, ax = plt.subplots(figsize=(10.5, 4.4)); ax.axis("off"); ax.set_xlim(0, 10.5); ax.set_ylim(0, 4.4); ax.grid(False)
    box(ax, 0.1, 1.7, 2.1, 1.3, "Both boards run all\nthe time: baseline,\nnotch, low-pass", "#ffffff")
    box(ax, 2.9, 1.7, 2.3, 1.3, "Per board, every sample:\nnoise = running median\nof |step|;  beat size\n= decaying peak", "#ffffff")
    box(ax, 5.9, 2.8, 2.3, 0.9, "Leads off, or stuck at\nan amplifier limit?", "#fdece5")
    box(ax, 5.9, 1.3, 2.3, 1.1, "quality = noise / beat size\nother < 0.6 x current,\nfor at least 4 s?", "#e8f0fb")
    box(ax, 8.7, 2.8, 1.7, 0.9, "Switch\nboard now", "#ffffff", bold=True); box(ax, 8.7, 1.3, 1.7, 1.1, "Switch\nboard", "#ffffff", bold=True)
    box(ax, 5.9, 0.15, 2.3, 0.7, "Otherwise stay", "#ffffff")
    arrow(ax, 2.2, 2.35, 2.9, 2.35); arrow(ax, 5.2, 2.6, 5.9, 3.2); arrow(ax, 5.2, 2.1, 5.9, 1.85)
    arrow(ax, 8.2, 3.25, 8.7, 3.25, "yes"); arrow(ax, 8.2, 1.85, 8.7, 1.85, "yes"); arrow(ax, 7.05, 1.3, 7.05, 0.85); ax.text(7.25, 1.02, "no", fontsize=8.5, color=INK2)
    ax.text(5.25, 4.2, "Figure 5: How the page chooses which board to show (both are always recorded)", ha="center", fontsize=11, color=INK, fontweight="bold")
    ax.text(0.1, 0.95, "A board counts as bad if its leads are off, it sits at an amplifier\nlimit for 25 samples in a row, or more than 20 % of the last\nhalf second was at a limit.", fontsize=8.5, color=INK2, va="top")
    save(fig, "fig5_switching.png")


# ---- Real-data figures (optional) ---------------------------------------------------------------------------------------
def fig_real(export_dir):
    d = Path(export_dir)
    spec = next(d.glob("*_spectra.csv")); rms = next(d.glob("*_band_rms_per_second.csv"))
    S = np.genfromtxt(spec, delimiter=",", names=True); f = S["freq_hz"]
    fig, ax = plt.subplots(figsize=(8, 3.9))
    ax.semilogy(f, S["a_rest"], color=BLUE); ax.semilogy(f, S["a_standing"], color=ORANGE)
    ax.axvspan(40, 55, color=ORANGE, alpha=0.10, lw=0); ax.axvline(60, color=INK2, ls=":", lw=1)
    ax.set_ylim(1e-2, 1e6)
    ax.text(47.5, 3e-2, "40-55 Hz hump", ha="center", fontsize=8.5, color=INK2); ax.text(60.8, 3e-2, "60 Hz mains", fontsize=8.5, color=INK2)
    ax.text(78, 6e0, "lying still (first 10 s)", color=BLUE, fontsize=9.5); ax.text(78, 1.2e3, "standing (33-47 s)", color=ORANGE, fontsize=9.5)
    ax.set_xlim(0, 125); ax.set_xlabel("frequency (Hz)"); ax.set_ylabel("power (pin mV$^2$/Hz)")
    ax.set_title("Figure 7: Board A noise spectrum, lying still versus standing", loc="left", fontsize=11, color=INK, fontweight="bold")
    save(fig, "fig7_spectrum_standing.png")

    R = np.genfromtxt(rms, delimiter=",", names=True); t = R["time_s"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    a1.semilogy(t, R["rms_a_b40_55"], color=ORANGE); a1.semilogy(t, R["rms_a_b55_65"], color=BLUE); a1.semilogy(t, R["rms_a_b5_15"], color=AQUA)
    a1.set_ylim(2e1, 2e3)
    a1.text(1, 330, "60 Hz mains", color=BLUE, fontsize=9.5); a1.text(23, 45, "5-15 Hz (where the QRS lives)", color=AQUA, fontsize=9.5); a1.text(33.5, 1500, "40-55 Hz", color=ORANGE, fontsize=9.5)
    a1.set_ylabel("RMS per second (pin mV)")
    a1.set_title("Figure 8: Noise by frequency band, and time spent at an amplifier limit", loc="left", fontsize=11, color=INK, fontweight="bold")
    a2.fill_between(t, 0, 100 * R["railfrac_a"], color=ORANGE, alpha=0.8, step="mid", lw=0); a2.set_ylabel("% of samples\nat a limit"); a2.set_xlabel("time (s)"); a2.set_xlim(0, t[-1] + 2)
    save(fig, "fig8_bands_over_time.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--real", help="export folder from export_for_matlab.py"); a = ap.parse_args()
    fig_system(); fig_aliasing(); fig_zero_phase(); fig_bandwidth(); fig_switching()
    if a.real:
        fig_real(a.real)
