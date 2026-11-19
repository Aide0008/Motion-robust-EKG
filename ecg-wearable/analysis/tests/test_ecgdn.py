"""Checks for ecgdn.py. Run from the analysis/ folder:  python -m pytest -q"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import lfilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import ecgdn as dn                      # noqa: E402
import make_synthetic as syn            # noqa: E402


def snr_db(truth, est):
    return 10 * np.log10(np.sum(truth ** 2) / np.sum((est - truth) ** 2))


# ---- filters ---------------------------------------------------------------------------------
def test_steady_state_start_has_no_transient():
    x = np.full(500, 3.7)
    assert np.allclose(dn.filtfilt(x, [("lp", 40.0)]), 3.7, atol=1e-9)       # DC passes a low-pass untouched
    assert np.allclose(dn.filtfilt(x, [("hp", 0.5)]), 0.0, atol=1e-9)        # DC is removed by a high-pass, from sample 0


def test_filtfilt_is_zero_phase_but_one_pass_is_not():
    n = 1000
    x = np.zeros(n)
    x[500] = 1.0                                                             # an impulse at sample 500
    b, a = dn.design("lp", 20.0)
    assert np.argmax(lfilter(b, a, x)) > 500                                 # one pass delays the peak
    assert np.argmax(dn.filtfilt(x, [("lp", 20.0)])) == 500                  # forward+backward does not


def test_notch_kills_60hz_and_keeps_10hz():
    t = np.arange(0, 20, 1 / dn.FS)
    b, a = dn.design_notch(60.0)
    for f, lo, hi in [(60.0, 0.0, 0.02), (10.0, 0.97, 1.03)]:
        y = lfilter(b, a, np.sin(2 * np.pi * f * t))[int(5 * dn.FS):]        # skip start-up
        gain = np.sqrt(np.mean(y ** 2)) / np.sqrt(0.5)
        assert lo <= gain <= hi, (f, gain)


# ---- statistics and the Kalman smoother --------------------------------------------------------
def test_mad_sigma_recovers_gaussian_sigma():
    x = np.random.default_rng(0).standard_normal(200000) * 0.37
    assert abs(dn.mad_sigma(x) - 0.37) / 0.37 < 0.02


def test_mad_sigma_ignores_a_few_big_spikes():
    rng = np.random.default_rng(1)
    x = rng.standard_normal(10000) * 0.1
    x[::100] = 5.0                                                           # 1 % huge spikes (like QRS complexes)
    assert abs(dn.mad_sigma(x) - 0.1) < 0.02 < np.std(x) - 0.1               # the std is wrecked, the MAD is not


def test_kalman_reproduces_a_noiseless_ramp():
    n = 400
    y = 0.01 * np.arange(n)
    out = dn.kalman_rts(y, np.full(n, 1e-4), np.full(n, 300.0))
    err = np.abs(out - y)
    assert np.max(err[10:-10]) < 1e-3                                        # a straight line is exactly in the model
    assert np.max(err) < 5e-3                                                # the first samples absorb the 'slope unknown' start


def test_kalman_smooths_noise_around_a_slow_wave():
    rng = np.random.default_rng(2)
    t = np.arange(0, 8, 1 / dn.FS)
    truth = np.sin(2 * np.pi * 0.5 * t)
    y = truth + 0.2 * rng.standard_normal(len(t))
    out = dn.kalman_rts(y, np.full(len(t), 0.04), np.full(len(t), 300.0))
    assert np.sqrt(np.mean((out - truth) ** 2)) < 0.5 * np.sqrt(np.mean((y - truth) ** 2))


# ---- the whole denoiser on the synthetic recording ------------------------------------------------
@pytest.fixture(scope="module")
def synth():
    t, truth, A, B = syn.make(30, seed=1)
    return t, truth, A


def test_denoiser_improves_snr_and_keeps_r_waves(synth):
    t, truth, A = synth
    sel = (t >= 8) & (t < 24)                                                # 2 s of rest either side of the burst
    ref = 0.8 * truth[sel] + 0.15 * np.sin(2 * np.pi * 0.25 * t[sel])        # what board A would read with no noise
    res = dn.denoise_run(A[sel])
    before, after = snr_db(ref, A[sel]), snr_db(ref, res["out"])
    assert after > before + 1.0, (before, after)
    # R waves must not be flattened: compare the tallest samples around each true beat
    beats = np.arange(np.ceil(t[sel][0] / 0.9), np.floor(t[sel][-1] / 0.9)) * 0.9
    idx = [int(round((b - t[sel][0]) * dn.FS)) for b in beats[2:-2]]
    kept = [res["out"][i - 3:i + 4].max() / ref[i - 3:i + 4].max() for i in idx]
    assert np.median(kept) > 0.9, kept


def test_beat_detector_and_bpm(synth):
    t, truth, _ = synth
    beats = dn.detect_beats(0.8 * truth)
    true_beats = np.arange(1, int(t[-1] / 0.9)) * 0.9
    found = sum(any(abs(b / dn.FS - tb) < 0.05 for b in beats) for tb in true_beats)
    assert found >= len(true_beats) - 1
    assert abs(dn.bpm_from_beats(beats) - 60 / 0.9) < 1.5


# ---- Python == JavaScript ----------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_python_matches_the_javascript_in_the_web_page(synth):
    t, truth, A = synth
    x = (0.8 * truth + 0.1 * np.random.default_rng(3).standard_normal(len(t)))[: 12 * int(dn.FS)]
    r = subprocess.run(["node", str(HERE / "js_reference.js")], input=json.dumps(x.tolist()),
                       capture_output=True, text=True, check=True)
    js = json.loads(r.stdout)
    py = dn.denoise_run(x)["out"]
    assert np.max(np.abs(np.array(js["out"]) - py)) < 1e-6
    assert list(js["beats"]) == [int(b) for b in dn.detect_beats(x)]
