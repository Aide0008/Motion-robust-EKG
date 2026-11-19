"""
demo_denoise.py - run the denoiser on the synthetic recording and save a before/after figure.

usage:  python demo_denoise.py          (writes ../docs/figures/denoise_demo.png and prints the numbers)
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ecgdn as dn
import make_synthetic as syn


def snr_db(truth, est):
    return 10 * np.log10(np.sum(truth ** 2) / np.sum((est - truth) ** 2))


t, truth, A, B = syn.make(30, seed=1)
base = 0.15 * np.sin(2 * np.pi * 0.25 * t)
ref = 0.8 * truth + base                                      # what board A reads with no noise at all
sel = (t >= 8) & (t < 24)                                     # the burst (10-20 s) plus rest either side
res = dn.denoise_run(A[sel])
tt = t[sel]

burst = (tt >= 10) & (tt < 20)
print(f"board A, 8-24 s : SNR before {snr_db(ref[sel], A[sel]):5.1f} dB   after {snr_db(ref[sel], res['out']):5.1f} dB")
print(f"   inside burst : SNR before {snr_db(ref[sel][burst], A[sel][burst]):5.1f} dB   after {snr_db(ref[sel][burst], res['out'][burst]):5.1f} dB")
print(f"noise meter: {np.median(res['sig'][~burst]):.3f} mV at rest, {np.median(res['sig'][burst]):.3f} mV in the burst")
print("beats found by the detector on the noisy signal:", len(dn.detect_beats(A[sel])), "(true:", int((tt[-1] - tt[0]) / 0.9), ")")

fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
ax[0].plot(tt, A[sel], lw=0.7, color="0.55", label="board A (noisy)")
ax[0].plot(tt, ref[sel], lw=1.0, color="k", label="true signal (known: synthetic)")
ax[0].legend(loc="upper right"); ax[0].set_ylabel("mV")
ax[1].plot(tt, A[sel], lw=0.6, color="0.8")
ax[1].plot(tt, res["out"], lw=1.1, color="tab:red", label="Kalman + RTS output")
ax[1].plot(tt, ref[sel], lw=0.8, color="k", ls="--", label="true signal")
ax[1].legend(loc="upper right"); ax[1].set_ylabel("mV")
ax[2].plot(tt, res["sig"], color="tab:blue", label="noise meter  sigma (mV)")
ax[2].fill_between(tt, 0, res["sig"].max() * res["mask"], color="tab:orange", alpha=0.3, step="mid", label="QRS mask (q large)")
ax[2].legend(loc="upper right"); ax[2].set_xlabel("time (s)")
fig.suptitle("Denoiser on a synthetic recording: muscle-like noise burst from 10 s to 20 s")
fig.tight_layout(); fig.savefig("../docs/figures/denoise_demo.png", dpi=110)
print("wrote ../docs/figures/denoise_demo.png")
