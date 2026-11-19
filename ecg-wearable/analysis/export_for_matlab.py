"""
export_for_matlab.py - turn a recording from the web page into plain CSV files and one .mat file for MATLAB.

usage:
    python export_for_matlab.py RECORDING.csv --out export_folder
    python export_for_matlab.py RECORDING.csv --out export_folder --segments "rest=0-10,tap=11-20,standing=30-47"

Segment times are seconds from the start of the recording. Everything is in the same raw units the ESP32 reports:
"pin mV" = millivolts at the amplifier OUTPUT pin. Divide by the module gain (1100) to get millivolts at the
electrode.

Files written (NAME = recording file name without .csv):
    NAME_raw.csv               time_s, mv_a, mv_b, lo_a, lo_b, mux_ch   (what the ESP32 sent)
    NAME_bands_timeseries.csv  time_s + the signal band-passed into 6 frequency bands, for each board
    NAME_band_rms_per_second.csv   RMS of each band in every 1 s window + share of samples stuck at a rail
    NAME_spectra.csv           Welch power spectral density of every segment, every board (pin mV^2 / Hz)
    NAME.mat                   all of the above as MATLAB variables (open with  load('NAME.mat') )
    README_export.txt          what each column means
"""
import argparse
from pathlib import Path

import numpy as np
from scipy.io import savemat
from scipy.signal import butter, sosfiltfilt, welch

FS = 250.0
SAT_HI, SAT_LO = 3100, 170                      # the ADC/amplifier output is pinned at a limit beyond these (pin mV)
BANDS = [("b0p5_5", 0.5, 5.0, "slow: drift, P and T waves, motion"),
         ("b5_15", 5.0, 15.0, "most of the QRS complex"),
         ("b15_40", 15.0, 40.0, "QRS detail + muscle noise"),
         ("b40_55", 40.0, 55.0, "the unexplained 45-50 Hz band seen while standing"),
         ("b55_65", 55.0, 65.0, "60 Hz mains hum"),
         ("b65_125", 65.0, 124.0, "high-frequency noise up to Nyquist")]


def load(path):
    rows, header = [], None
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line[0].isalpha():
            header = line.split(",")
            continue
        rows.append(line.split(","))
    def col(i, default=np.nan, cast=float):
        out = []
        for r in rows:
            v = r[i] if i < len(r) and r[i] != "" else None
            out.append(cast(v) if v is not None else default)
        return np.array(out)
    t = col(0) / 1000.0
    d = dict(t=t - t[0], a=col(1), lo_a=col(2, 0) + 2 * col(3, 0), mux=col(4, -1))
    d["b"] = col(5)
    d["lo_b"] = np.nan_to_num(col(6, 0)) + 2 * np.nan_to_num(col(7, 0))
    d["two_board"] = bool(np.isfinite(d["b"]).any())
    d["t_esp"] = t
    return d


def parse_segments(text, duration):
    if not text:                                # default: consecutive 10 s windows
        edges = np.arange(0, duration, 10.0)
        return [(f"w{int(s):03d}_{int(min(s + 10, duration)):03d}", s, min(s + 10, duration)) for s in edges if duration - s > 3]
    out = []
    for part in text.split(","):
        name, rng = part.split("=")
        s, e = rng.split("-")
        out.append((name.strip(), float(s), float(e)))
    return out


def bandpass(x, lo, hi):
    return sosfiltfilt(butter(4, [lo, hi], btype="band", fs=FS, output="sos"), x - np.nanmedian(x))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording")
    ap.add_argument("--out", default="export")
    ap.add_argument("--segments", default="")
    args = ap.parse_args()

    name = Path(args.recording).stem
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    d = load(args.recording)
    t = d["t"]; n = len(t)
    boards = [("a", d["a"])] + ([("b", d["b"])] if d["two_board"] else [])
    segs = parse_segments(args.segments, t[-1])

    # 1. raw
    with open(out / f"{name}_raw.csv", "w") as f:
        f.write("time_s,mv_a,mv_b,lo_a,lo_b,mux_ch\n")
        for i in range(n):
            f.write(f"{t[i]:.4f},{d['a'][i]:g},{'' if np.isnan(d['b'][i]) else format(d['b'][i], 'g')},{int(d['lo_a'][i])},{int(d['lo_b'][i])},{int(d['mux'][i]) if d['mux'][i] >= 0 else ''}\n")

    # 2. band-passed time series (zero-phase 4th-order Butterworth band-pass on each band)
    series = {}
    for bn, x in boards:
        for key, lo, hi, _ in BANDS:
            y = np.full(n, np.nan); ok = np.isfinite(x)
            y[ok] = bandpass(x[ok], lo, hi)
            series[f"{bn}_{key}"] = y
    with open(out / f"{name}_bands_timeseries.csv", "w") as f:
        keys = list(series)
        f.write("time_s," + ",".join(keys) + "\n")
        for i in range(n):
            f.write(f"{t[i]:.4f}," + ",".join("" if np.isnan(series[k][i]) else f"{series[k][i]:.3f}" for k in keys) + "\n")

    # 3. RMS of each band per second + rail fraction
    nsec = int(t[-1])
    rms = {"time_s": np.arange(nsec) + 0.5}
    for bn, x in boards:
        for key, *_ in BANDS:
            y = series[f"{bn}_{key}"]
            rms[f"rms_{bn}_{key}"] = np.array([np.sqrt(np.nanmean(y[(t >= s) & (t < s + 1)] ** 2)) for s in range(nsec)])
        rms[f"railfrac_{bn}"] = np.array([np.mean((x[(t >= s) & (t < s + 1)] >= SAT_HI) | (x[(t >= s) & (t < s + 1)] <= SAT_LO)) for s in range(nsec)])
        rms[f"mean_{bn}"] = np.array([np.nanmean(x[(t >= s) & (t < s + 1)]) for s in range(nsec)])
    with open(out / f"{name}_band_rms_per_second.csv", "w") as f:
        keys = list(rms)
        f.write(",".join(keys) + "\n")
        for i in range(nsec):
            f.write(",".join(f"{rms[k][i]:.4f}" for k in keys) + "\n")

    # 4. Welch spectra per segment (same frequency axis for all: 1024-sample windows, 50 % overlap, Hann)
    nper = 1024
    freqs = np.fft.rfftfreq(nper, 1 / FS)
    spec, cols = [], []
    for sn, s, e in segs:
        m = (t >= s) & (t < e)
        for bn, x in boards:
            xs = x[m]; xs = xs[np.isfinite(xs)]
            if len(xs) < 256:
                continue
            f_, p = welch(xs - xs.mean(), fs=FS, nperseg=min(nper, len(xs)), noverlap=min(nper, len(xs)) // 2, window="hann")
            spec.append(np.interp(freqs, f_, p)); cols.append(f"{bn}_{sn}")
    spec = np.array(spec).T
    with open(out / f"{name}_spectra.csv", "w") as f:
        f.write("freq_hz," + ",".join(cols) + "\n")
        for i in range(len(freqs)):
            f.write(f"{freqs[i]:.4f}," + ",".join(f"{spec[i, j]:.4f}" for j in range(spec.shape[1])) + "\n")

    # 5. .mat
    mat = dict(fs=FS, t=t, mv_a=d["a"], mv_b=d["b"], lo_a=d["lo_a"], lo_b=d["lo_b"], mux_ch=d["mux"],
               band_names=np.array([b[0] for b in BANDS], dtype=object), band_edges_hz=np.array([[b[1], b[2]] for b in BANDS]),
               spec_freq_hz=freqs, spec_psd=spec, spec_names=np.array(cols, dtype=object),
               segments=np.array([[s, e] for _, s, e in segs]), segment_names=np.array([s[0] for s in segs], dtype=object),
               gain=1100.0, sat_hi_mv=SAT_HI, sat_lo_mv=SAT_LO)
    for k, v in series.items():
        mat[k] = v
    for k, v in rms.items():
        mat["sec_" + k] = v
    savemat(out / f"{name}.mat", mat, do_compression=True)

    # 6. readme
    with open(out / "README_export.txt", "w") as f:
        f.write(f"""Export of {Path(args.recording).name}
samples: {n}   duration: {t[-1]:.1f} s   sample rate: {FS:g} Hz   boards: {'A and B' if d['two_board'] else 'A only'}

Units: 'pin mV' = millivolts at the amplifier output pin (what the ESP32 ADC reads). electrode mV = pin mV / gain (gain 1100).
The ADC/amplifier is pinned at a limit above {SAT_HI} or below {SAT_LO} pin mV - the real signal is lost there.

{name}_raw.csv            time_s, mv_a, mv_b (pin mV), lo_a, lo_b (leads-off: bit0 = LO+, bit1 = LO-), mux_ch (single-board mux recordings)
{name}_bands_timeseries.csv  zero-phase 4th-order Butterworth band-pass of each board, pin mV, one column per board x band
{name}_band_rms_per_second.csv  RMS of those bands per second; railfrac_* = share of samples at a limit; mean_* = mean level (pin mV)
{name}_spectra.csv        Welch power spectral density (pin mV^2/Hz), column = board_segment; freq axis 0-125 Hz, 0.244 Hz steps
{name}.mat                everything as MATLAB variables (series named a_b40_55 etc., per-second ones start with sec_)

Bands:
""" + "\n".join(f"  {k:8s} {lo:g}-{hi:g} Hz   {desc}" for k, lo, hi, desc in BANDS) + "\n\nSegments (seconds):\n" + "\n".join(f"  {sn}: {s:g}-{e:g}" for sn, s, e in segs) + "\n")
    print(f"wrote {len(list(out.iterdir()))} files to {out}")


if __name__ == "__main__":
    main()
