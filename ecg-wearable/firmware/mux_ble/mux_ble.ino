// ECG with 2-electrode mux, "only switch when worn" logic, and switching when the signal gets NOISY
// v4: sends the same text lines over BLE (Bluetooth) AND over USB serial.
// Needs the ECG wire on an ADC1 pin (32-39); ADC2 pins stop working when Bluetooth is on.
// Arduino IDE: if it says "Sketch too big", choose Tools > Partition Scheme > "Huge APP".
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <stdarg.h>

#define BLE_NAME "ECG-ESP32"
#define SVC_UUID "6e400001-b5a3-f393-e0a9-e50e24dcca9e"   // Nordic UART service
#define TX_UUID  "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   // notifications ESP32 -> page

BLEServer* bleServer = nullptr;
BLECharacteristic* bleTx = nullptr;
volatile bool bleUp = false;
volatile bool clearQ = false;
volatile unsigned long bleDownAt = 0;
bool bleEverUp = false;

// Text waiting to be sent over BLE. If the link drops, the last few seconds are kept and sent on reconnect.
const size_t QSIZE = 24576;                 // about 5 s of data
static char q[QSIZE];
size_t qHead = 0, qTail = 0;                // data lives in [qTail, qHead)

void bleQueue(const char* s, size_t n) {
  for (size_t i = 0; i < n; i++) {
    size_t nh = (qHead + 1) % QSIZE;
    if (nh == qTail) {                      // full: throw away the oldest line
      while (qTail != qHead && q[qTail] != '\n') qTail = (qTail + 1) % QSIZE;
      if (qTail != qHead) qTail = (qTail + 1) % QSIZE;
    }
    q[qHead] = s[i]; qHead = nh;
  }
}

void emitf(const char* fmt, ...) {          // print to USB and queue for Bluetooth
  char b[160];
  va_list a; va_start(a, fmt);
  int n = vsnprintf(b, sizeof b, fmt, a);
  va_end(a);
  if (n <= 0) return;
  if (n > (int)sizeof b - 1) n = sizeof b - 1;
  Serial.write((const uint8_t*)b, n);
  bleQueue(b, n);
}

class SrvCb : public BLEServerCallbacks {
  void onConnect(BLEServer*) {
    if (!bleEverUp || millis() - bleDownAt > 8000) clearQ = true;   // don't send stale data after a long gap
    bleEverUp = true; bleUp = true;
  }
  void onDisconnect(BLEServer*) {
    bleUp = false; bleDownAt = millis();
    BLEDevice::startAdvertising();          // be findable again
  }
};

void bleFlush() {
  static unsigned long last = 0;
  if (clearQ) { qTail = qHead; clearQ = false; }
  if (!bleUp) return;
  unsigned long m = millis();
  if (m - last < 20) return;
  last = m;
  uint16_t mtu = bleServer->getPeerMTU(bleServer->getConnId());
  size_t pay = (mtu > 23 && mtu <= 517) ? mtu - 3 : 20;
  for (int k = 0; k < 3 && qTail != qHead; k++) {
    uint8_t buf[517]; size_t n = 0;
    while (n < pay && qTail != qHead) { buf[n++] = (uint8_t)q[qTail]; qTail = (qTail + 1) % QSIZE; }
    bleTx->setValue(buf, n);
    bleTx->notify();
  }
}

void bleBegin() {
  BLEDevice::init(BLE_NAME);
  BLEDevice::setMTU(247);
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new SrvCb());
  BLEService* svc = bleServer->createService(SVC_UUID);
  bleTx = svc->createCharacteristic(TX_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  bleTx->addDescriptor(new BLE2902());
  svc->start();
  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SVC_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();
}

// Output per line: time_ms, output_mV, LO+, LO-, active_channel
// On a switch it also prints:  S,switch_ms,bad_stretch_start_ms

// Mux select pins
// ALL pins are on the LEFT side of a 30-pin ESP32 (ADC1 pins keep working with WiFi/Bluetooth on)
const int S0 = 14, S1 = 25, S2 = 27, S3 = 26;

// 3.3V for the AD8232 + mux comes from this pin (no 3V3 pin needed). Wire AD8232 3.3V, SDN and mux VCC/EN-pull here.
const int PWR_PIN = 32;

// ECG
const int ECG_PIN  = 33;    // AD8232 OUTPUT (ADC1)
const int LO_PLUS  = 34;    // input-only pin, fine for leads-off
const int LO_MINUS = 35;    // input-only pin, fine for leads-off
const unsigned long SAMPLE_US = 4000;   // 250 samples per second

const int CH_A = 0;
const int CH_B = 1;

// ---- Tuning ----
const float JUMP_MV = 700;               // distance from baseline that counts as "too big" (output mV)
const unsigned long BAD_MS = 150;        // must stay out of range this long (a QRS is ~100 ms)
const float CLEAR_FRAC = 0.7;            // must come back inside 70% of JUMP_MV to end a bad spell
const int RAIL_HI = 2800;                // output this high or...
const int RAIL_LO = 400;                 // ...this low = amplifier saturated (motion / bad contact)
const unsigned long RAIL_MS = 100;       // saturated this long while leads read 'on' = bad
const unsigned long ESTABLISH_MS = 3000; // signal must be calm and leads on for this long = "solid baseline"
const unsigned long OFF_MS = 1500;       // leads-off flag high this long = taken off (no switching)
const int DROPOUTS = 3;                  // this many on/off flickers...
const unsigned long DROPOUT_WINDOW_MS = 5000;  // ...within this time = poor contact
const float TAU_SEARCH = 0.5;            // baseline follow speed while settling (seconds)
const float TAU_WORN   = 1.5;            // baseline follow speed once established (seconds)

// ---- Noise-based switching (muscle flexing makes the line fuzzy without making it jump) ----
// Noise = a running median of how much the reading changes from one sample to the next (output mV per sample).
// Your resting noise measured about 15; flexing the pecs measured 25 to 105.
const float NOISE_RATE  = 0.006;         // how fast the noise estimate moves (bigger = faster, twitchier)
const float NOISE_RATIO = 2.0;           // noisy = this many times this electrode's own resting noise...
const float NOISE_FLOOR = 30;            // ...but never call it noisy below this
const float NOISE_ABS   = 60;            // above this it is noisy no matter what the resting level was
const float NOISE_CLEAR = 0.7;           // back below 70% of the limit = the noise spell is over
const unsigned long NOISE_MS = 1000;     // must stay noisy this long before switching
const unsigned long DWELL_MIN_MS = 8000; // after any switch, stay at least this long before a noise switch
const unsigned long DWELL_MAX_MS = 60000;// if noise switches keep happening, the wait doubles up to this
const float FORGET_MS = 30000.0;         // half-life of what we remember about the electrode we left

enum State { SEARCHING, WORN };
State state = SEARCHING;
int activeCh = CH_A;

float baseline = 0;
bool baselineReady = false;
unsigned long stableSince = 0;           // calm signal + leads on, since when
unsigned long badSince = 0; bool inBad = false;
unsigned long railSince = 0; bool railed = false;
unsigned long loSince = 0;  bool loHigh = false;   // leads-off flag high continuously since
unsigned long dropoutT[DROPOUTS]; int dropoutN = 0;

float noiseMed = 15;                     // current noise estimate
int lastV = 0; bool skipNoise = true;
float noiseRef[2] = {0, 0};              // each electrode's own resting noise, learned when it becomes 'worn'
float noiseLeft[2] = {0, 0};             // noise on each electrode when we last left it
unsigned long leftAt[2] = {0, 0}; bool visited[2] = {false, false};
unsigned long noisySince = 0; bool inNoisy = false;
unsigned long lastSwitchMs = 0, lastNoiseSwitch = 0, dwellMs = DWELL_MIN_MS;

void selectChannel(int ch) {
  noiseLeft[activeCh] = noiseMed; leftAt[activeCh] = millis(); visited[activeCh] = true;   // remember how it was when we left
  digitalWrite(S0, ch & 1);
  digitalWrite(S1, (ch >> 1) & 1);
  digitalWrite(S2, (ch >> 2) & 1);
  digitalWrite(S3, (ch >> 3) & 1);
  delayMicroseconds(50);
  activeCh = ch;
  state = SEARCHING;                     // new channel: prove itself again before any switching
  baselineReady = false;
  stableSince = millis();
  inBad = false; railed = false; loHigh = false; dropoutN = 0;
  if (noiseRef[ch] > 0) noiseMed = noiseRef[ch];   // start from what this electrode usually reads
  skipNoise = true; inNoisy = false; lastSwitchMs = millis();
}

// Remember a short on/off flicker; true when there have been too many lately
bool recordDropout(unsigned long now) {
  if (dropoutN == DROPOUTS) {
    for (int i = 1; i < DROPOUTS; i++) dropoutT[i - 1] = dropoutT[i];
    dropoutN--;
  }
  dropoutT[dropoutN++] = now;
  return dropoutN == DROPOUTS && (now - dropoutT[0]) <= DROPOUT_WINDOW_MS;
}

void setup() {
  Serial.begin(115200);
  pinMode(PWR_PIN, OUTPUT); digitalWrite(PWR_PIN, HIGH);   // power the AD8232 + mux
  delay(500);                                              // let the amplifier settle
  pinMode(S0, OUTPUT); pinMode(S1, OUTPUT);
  pinMode(S2, OUTPUT); pinMode(S3, OUTPUT);
  pinMode(LO_PLUS, INPUT);
  pinMode(LO_MINUS, INPUT);
  selectChannel(CH_A);
  bleBegin();
}

void loop() {
  bleFlush();
  static unsigned long next = micros();
  if ((long)(micros() - next) < 0) return;
  next += SAMPLE_US;

  unsigned long now = millis();
  int v  = analogReadMilliVolts(ECG_PIN);
  int lp = digitalRead(LO_PLUS);
  int lm = digitalRead(LO_MINUS);
  bool lo = (lp == 1 || lm == 1);

  emitf("%lu,%d,%d,%d,%d\n", now, v, lp, lm, activeCh);

  // Noise estimate: running median of |change per sample| (skips the step the mux itself causes)
  if (skipNoise) skipNoise = false;
  else if (!lo) {
    float d = fabs((float)(v - lastV));
    noiseMed *= (d > noiseMed) ? (1 + NOISE_RATE) : (1 - NOISE_RATE);
    if (noiseMed < 1) noiseMed = 1;
  }
  lastV = v;

  // Follow the resting level, but not while the leads-off flag is on (the output sits at the rail then)
  // Once worn, FREEZE the baseline while the signal is far from it, so a long excursion isn't absorbed
  bool freezeBase = (state == WORN) && baselineReady && fabs(v - baseline) > JUMP_MV * 0.5;
  if (!lo && !freezeBase) {
    if (!baselineReady) { baseline = v; baselineReady = true; }
    float tau = (state == WORN) ? TAU_WORN : TAU_SEARCH;
    baseline += (v - baseline) * ((SAMPLE_US / 1e6) / tau);
  }
  float dev = baselineReady ? fabs(v - baseline) : 0;

  // Status line for tuning (the website ignores lines starting with #). Delete this block if you don't want it.
  static unsigned long lastDbg = 0;
  if (now - lastDbg >= 500) {
    lastDbg = now;
    emitf("# %s ch=%d lo=%d dev=%.0f noise=%.0f limit=%.0f\n", state == WORN ? "WORN" : "SEARCHING", activeCh, lo, dev,
                  noiseMed, fmax(NOISE_RATIO * noiseRef[activeCh], NOISE_FLOOR));
  }

  // Track how long the leads-off flag has been on
  bool dropoutPoor = false;
  if (lo) {
    if (!loHigh) { loHigh = true; loSince = now; }
  } else if (loHigh) {
    loHigh = false;
    if (state == WORN && (now - loSince) < OFF_MS) dropoutPoor = recordDropout(now);
  }
  bool takenOff = loHigh && (now - loSince) >= OFF_MS;

  // Far from baseline while leads read 'on'. Counts only once it has lasted (a heartbeat peak is too short).
  // Hysteresis: the spell ends only when the signal is back well inside the limit.
  if (!lo && dev > JUMP_MV) {
    if (!inBad) { inBad = true; badSince = now; }
  } else if (dev < JUMP_MV * CLEAR_FRAC) {
    inBad = false;
  }
  bool farTooLong = inBad && (now - badSince >= BAD_MS);

  if (state == SEARCHING) {
    // Never switch here. Just wait for a calm signal with the leads on.
    bool unstable = lo || !baselineReady || farTooLong;
    if (unstable) stableSince = now;
    else if (now - stableSince >= ESTABLISH_MS) {
      state = WORN; inBad = false; dropoutN = 0;
      noiseRef[activeCh] = noiseMed;       // this electrode's own resting noise
      inNoisy = false;
    }
  } else {
    if (takenOff) {                      // leads came off: stay on this channel, go back to waiting
      state = SEARCHING; stableSince = now; inBad = false;
    } else {
      // (b) amplifier pinned at a rail while leads read 'on'
      bool atRail = !lo && (v > RAIL_HI || v < RAIL_LO);
      if (atRail) { if (!railed) { railed = true; railSince = now; } }
      else railed = false;

      bool railBad = railed && now - railSince >= RAIL_MS;

      // (c) noisy: muscle flexing, motion. Only switch if the other electrode looked quieter, and not too often.
      float limit = fmax(NOISE_RATIO * noiseRef[activeCh], NOISE_FLOOR);
      bool noisyNow = !lo && (noiseMed > limit || noiseMed > NOISE_ABS);
      if (noisyNow) { if (!inNoisy) { inNoisy = true; noisySince = now; } }
      else if (noiseMed < limit * NOISE_CLEAR && noiseMed < NOISE_ABS * NOISE_CLEAR) inNoisy = false;
      if (!inNoisy && !lo && noiseMed < 1.5 * noiseRef[activeCh])          // calm: let the resting level follow slowly
        noiseRef[activeCh] += (noiseMed - noiseRef[activeCh]) * ((SAMPLE_US / 1e6) / 30.0);
      int other = (activeCh == CH_A) ? CH_B : CH_A;
      float otherEst = 0;                                                    // what we expect the other electrode to read now
      if (visited[other]) {
        float k = powf(0.5f, (now - leftAt[other]) / FORGET_MS);
        otherEst = noiseRef[other] + (noiseLeft[other] - noiseRef[other]) * k;
      }
      bool otherBetter = !visited[other] || otherEst < noiseMed * 0.7;
      bool noiseBad = inNoisy && (now - noisySince >= NOISE_MS) && (now - lastSwitchMs >= dwellMs) && otherBetter;

      if (dropoutPoor || farTooLong || railBad || noiseBad) {
        // Tell the website when the bad stretch began, so it can erase it before it is drawn
        unsigned long badStart = now;
        if (farTooLong && badSince < badStart) badStart = badSince;
        if (railBad && railSince < badStart)   badStart = railSince;
        if (dropoutPoor && loSince < badStart) badStart = loSince;
        if (noiseBad) {
          unsigned long ns = noisySince > 1000 ? noisySince - 1000 : 0;       // the noise began a little before it was noticed
          if (ns < badStart) badStart = ns;
          dwellMs = (now - lastNoiseSwitch < 30000) ? (dwellMs * 2 > DWELL_MAX_MS ? DWELL_MAX_MS : dwellMs * 2) : DWELL_MIN_MS;
          lastNoiseSwitch = now;
        }
        emitf("S,%lu,%lu\n", now, badStart);
        selectChannel(activeCh == CH_A ? CH_B : CH_A);   // poor contact: try the other electrode
      }
    }
  }
}
