// Two AD8232 boards read at the same time (no multiplexer), sent over Bluetooth AND USB.
// Output per line:  time_ms, mvA, LO+A, LO-A, mvB, LO+B      (mv = amplifier output at the pin, in mV)
//
// Wiring (all pins work with Bluetooth on):
//   25  -> 3.3 V for both boards (AD8232 3.3V + SDN)        GND -> GND of both boards
//   33  -> board A OUTPUT      34 -> board A LO+      35 -> board A LO-
//   32  -> board B OUTPUT      26 -> board B LO+      (board B LO- not connected; LA is shared)
// Electrodes: A.RA = electrode 1, B.RA = electrode 2, LA and RL shared by both boards.
//
// Arduino IDE: if it says "Sketch too big", choose Tools > Partition Scheme > "Huge APP".
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <stdarg.h>

const int PWR_PIN = 25;
const int OUT_A = 33, LOP_A = 34, LOM_A = 35;
const int OUT_B = 32, LOP_B = 26;
const unsigned long SAMPLE_US = 4000;   // 250 samples per second
const int OVERSAMPLE = 4;               // average this many ADC reads per sample (less ADC noise)

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
const size_t QSIZE = 24576;
static char q[QSIZE];
size_t qHead = 0, qTail = 0;            // data lives in [qTail, qHead)

void bleQueue(const char* s, size_t n) {
  for (size_t i = 0; i < n; i++) {
    size_t nh = (qHead + 1) % QSIZE;
    if (nh == qTail) {                  // full: throw away the oldest line
      while (qTail != qHead && q[qTail] != '\n') qTail = (qTail + 1) % QSIZE;
      if (qTail != qHead) qTail = (qTail + 1) % QSIZE;
    }
    q[qHead] = s[i]; qHead = nh;
  }
}

void emitf(const char* fmt, ...) {      // print to USB and queue for Bluetooth
  char b[96];
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
    BLEDevice::startAdvertising();      // be findable again
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

int readMv(int pin) {
  long sum = 0;
  for (int i = 0; i < OVERSAMPLE; i++) sum += analogReadMilliVolts(pin);
  return (int)(sum / OVERSAMPLE);
}

void setup() {
  Serial.begin(460800);
  pinMode(PWR_PIN, OUTPUT); digitalWrite(PWR_PIN, HIGH);   // power both AD8232 boards
  delay(500);                                              // let the amplifiers settle
  pinMode(LOP_A, INPUT); pinMode(LOM_A, INPUT); pinMode(LOP_B, INPUT);
  bleBegin();
}

void loop() {
  bleFlush();
  static unsigned long next = micros();
  if ((long)(micros() - next) < 0) return;
  next += SAMPLE_US;
  if ((long)(micros() - next) > 100000) next = micros();   // fell far behind (e.g. long BLE call): don't try to catch up

  unsigned long now = millis();
  int a = readMv(OUT_A), b = readMv(OUT_B);
  emitf("%lu,%d,%d,%d,%d,%d\n", now, a, digitalRead(LOP_A), digitalRead(LOM_A), b, digitalRead(LOP_B));
}
