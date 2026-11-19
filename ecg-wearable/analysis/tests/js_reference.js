// Runs the denoiser that is embedded in web/ecg_monitor.html on a signal read from stdin (JSON array of mV)
// and prints JSON: { out: [...], beats: [...] }.  Used by test_ecgdn.py to check Python == JavaScript.
const fs = require('fs'), path = require('path'), vm = require('vm');
const html = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'ecg_monitor.html'), 'utf8');
const a = html.indexOf('/* DENOISER START'), b = html.indexOf('/* DENOISER END */');
if (a < 0 || b < 0) { console.error('denoiser markers not found'); process.exit(2); }
const ctx = {}; vm.createContext(ctx);
vm.runInContext(html.slice(a, b) + '\nthis.DN = DN;', ctx);
const x = Float64Array.from(JSON.parse(fs.readFileSync(0, 'utf8')));
const r = ctx.DN.denoiseRun(x, 1);
process.stdout.write(JSON.stringify({ out: Array.from(r.out), beats: Array.from(ctx.DN.detectBeats(x)) }));
