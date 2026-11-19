% demo_kalman.m - the denoiser's core on made-up data, so you can play with q and R.
% Try: change q (how fast the signal may bend) and sigma (how noisy it is) and watch the smoothing change.
fs = 250; t = (0:1/fs:8)'; rng(1);
truth = sin(2*pi*0.5*t) + 0.4*sin(2*pi*3*t);
sigma = 0.2;  y = truth + sigma*randn(size(t));
q = 300;                                   % mV^2/s^3
out = kalman_rts(y, sigma^2*ones(size(t)), q*ones(size(t)), fs);
fprintf('RMS error  noisy: %.3f   smoothed: %.3f\n', rms(y-truth), rms(out-truth));
figure; plot(t,y,'Color',[.8 .8 .8]); hold on; plot(t,truth,'k','LineWidth',1); plot(t,out,'r','LineWidth',1.2);
legend('noisy','truth','Kalman + RTS'); xlabel('time (s)');
% Rule of thumb (docs/MATH.md 5.4), measured on this smoother: -3 dB frequency ~ 0.8 * (q / r)^(1/4) / (2*pi)
% where r = sigma^2 / fs is the measurement noise per unit time.
bw = 0.8 * (q/(sigma^2/fs))^(1/4)/(2*pi);  fprintf('rough effective bandwidth: %.1f Hz\n', bw);
