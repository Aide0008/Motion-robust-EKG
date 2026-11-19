% filter_chain.m - rebuild the page's signal chain in MATLAB:  baseline -> notch 60 Hz -> low-pass 40 Hz
% Compare with docs/MATH.md section 2-3. Needs the Signal Processing Toolbox.

file = 'NAME.mat';  S = load(file);
fs = double(S.fs);  t = S.t(:);  x = S.mv_a(:);
t0 = 0; t1 = 10;                               % seconds to look at
m  = t >= t0 & t < t1 & isfinite(x);  x = x(m); tm = t(m);

%% baseline tracker: first-order exponential, tau = 1.5 s  (the page's "Light" setting)
tau = 1.5; dt = 1/fs; alpha = 1 - exp(-dt/tau);
base = filter(alpha, [1 alpha-1], x, (1-alpha)*x(1));   % y[n] = y[n-1] + alpha (x[n] - y[n-1]), starts at x(1)
v = x - base;                                           % pin mV with the slow drift removed
fprintf('baseline tracker cutoff = %.3f Hz\n', 1/(2*pi*tau));

%% 60 Hz notch (Q = 20 -> 3 Hz wide) and 40 Hz Butterworth low-pass
w0 = 60/(fs/2);  [bn, an] = iirnotch(w0, w0/20);
[bl, al] = butter(2, 40/(fs/2));
y_causal = filter(bl, al, filter(bn, an, v));           % what the live page does (one pass, delays the signal)
y_zero   = filtfilt(bl, al, filtfilt(bn, an, v));       % zero phase (what Review does)

figure; hold on
plot(tm, v, 'Color', [.7 .7 .7], 'DisplayName', 'baseline removed');
plot(tm, y_causal, 'DisplayName', 'notch+LP, one pass');
plot(tm, y_zero,   'DisplayName', 'notch+LP, zero phase');
legend; xlabel('time (s)'); ylabel('pin mV'); title('compare: the one-pass trace lags the zero-phase one')

%% frequency responses
figure; freqz(bn, an, 1024, fs); title('60 Hz notch')
figure; freqz(bl, al, 1024, fs); title('40 Hz Butterworth low-pass')
