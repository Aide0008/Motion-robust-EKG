% explore_recording.m - look at a recording exported by analysis/export_for_matlab.py
% Needs the Signal Processing Toolbox (spectrogram, butter, filtfilt, iirnotch).
% Units: "pin mV" = millivolts at the amplifier output pin. Electrode mV = pin mV / 1100.

file = 'NAME.mat';                 % <-- change to the .mat you exported
S  = load(file);
fs = double(S.fs);  t = S.t(:);
a  = S.mv_a(:);     b = S.mv_b(:);
twoBoard = any(isfinite(b));
bands = cellstr(S.band_names);     % b0p5_5, b5_15, b15_40, b40_55, b55_65, b65_125
edges = S.band_edges_hz;           % [low high] of each band, Hz

%% 1. Raw signal, with the two amplifier limits drawn
figure('Name','raw'); hold on
plot(t, a, 'DisplayName','board A');
if twoBoard, plot(t, b, 'DisplayName','board B'); end
yline(double(S.sat_hi_mv),'r:'); yline(double(S.sat_lo_mv),'r:');
xlabel('time (s)'); ylabel('pin mV'); legend; title('raw output of the amplifier(s)')

%% 2. Power spectral density of every segment (the "noise at different Hz")
figure('Name','spectra'); hold on
names = cellstr(S.spec_names);
for j = 1:size(S.spec_psd,2)
    semilogy(S.spec_freq_hz, S.spec_psd(:,j), 'DisplayName', strrep(names{j},'_','\_'));
end
set(gca,'YScale','log'); xlim([0 125]); grid on; legend('Location','northeast')
xlabel('frequency (Hz)'); ylabel('PSD (pin mV^2 / Hz)'); title('spectrum per segment')
% Things to look for: 60 Hz mains peak, a hump near 45-50 Hz while standing, the slow
% (< 5 Hz) region where P and T waves live, and how all of it changes between segments.

%% 3. How much of each band is there, second by second
tt = S.sec_time_s(:)';
M  = nan(numel(bands), numel(tt));
for k = 1:numel(bands), M(k,:) = S.(['sec_rms_a_' bands{k}]); end
figure('Name','band RMS'); imagesc(tt, 1:numel(bands), 20*log10(M)); axis xy; colorbar
yticks(1:numel(bands)); yticklabels(arrayfun(@(k) sprintf('%g-%g Hz',edges(k,1),edges(k,2)), 1:numel(bands),'UniformOutput',false));
xlabel('time (s)'); title('board A: RMS per band per second (dB re 1 pin mV)')

%% 4. Spectrogram of board A (time on x, frequency on y)
x = a(isfinite(a)); x = x - mean(x);
figure('Name','spectrogram');
spectrogram(x, hann(256), 192, 512, fs, 'yaxis'); ylim([0 0.125]); title('board A spectrogram (frequency in kHz)')

%% 5. Do the two boards see the same disturbance?  (shared LA/RL -> yes, and redundancy fails)
if twoBoard
    for k = [4 5]   % the 40-55 Hz and 55-65 Hz bands
        ya = S.(['a_' bands{k}]); yb = S.(['b_' bands{k}]);
        ok = isfinite(ya) & isfinite(yb);
        c = corrcoef(ya(ok), yb(ok));
        fprintf('band %s: correlation between board A and B = %.2f\n', bands{k}, c(1,2));
    end
end

%% 6. Time spent at an amplifier limit
fprintf('A: %.1f %% of samples at a limit\n', 100*mean(a >= S.sat_hi_mv | a <= S.sat_lo_mv));
if twoBoard, fprintf('B: %.1f %% of samples at a limit\n', 100*mean(b >= S.sat_hi_mv | b <= S.sat_lo_mv)); end
