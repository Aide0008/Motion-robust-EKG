function out = kalman_rts(y, R, Q, fs)
% KALMAN_RTS  Kalman filter + Rauch-Tung-Striebel smoother for the integrated-random-walk model.
%   state x = [level; slope],  F = [1 dt; 0 1],  H = [1 0]
%   y(k) : measurements (mV)           R(k) : measurement noise variance (mV^2)
%   Q(k) : noise intensity driving the slope (mV^2/s^3) - larger = the signal may bend faster
%   Same algorithm as analysis/ecgdn.py and the page; see docs/MATH.md section 5.
y = y(:); R = R(:); Q = Q(:); n = numel(y); dt = 1/fs;
F = [1 dt; 0 1]; H = [1 0];
xf = zeros(2,n); Pf = zeros(2,2,n);       % filtered mean / covariance
xp = zeros(2,n); Pp = zeros(2,2,n);       % predicted mean / covariance
x = [y(1); 0]; P = [1 0; 0 10];           % start: level = first sample, slope unknown
for k = 1:n
    if k > 1
        q  = Q(k);
        Qd = q * [dt^3/3 dt^2/2; dt^2/2 dt];
        x  = F * x;
        P  = F * P * F' + Qd;
    end
    xp(:,k) = x;  Pp(:,:,k) = P;
    S = H * P * H' + R(k);
    K = P * H' / S;
    x = x + K * (y(k) - H * x);
    P = (eye(2) - K * H) * P;
    xf(:,k) = x;  Pf(:,:,k) = P;
end
xs = xf;                                   % backward (smoothing) pass
for k = n-1:-1:1
    C = Pf(:,:,k) * F' / Pp(:,:,k+1);
    xs(:,k) = xf(:,k) + C * (xs(:,k+1) - xp(:,k+1));
end
out = xs(1,:)';
end
