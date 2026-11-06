/**
 * BioSpine Master Unified Firmware v4.0  (XIAO ESP32-C6 edition)
 *
 * Hardware : Seeed Studio XIAO ESP32-C6 + MPU-6050 / GY-521
 * I2C      : SDA = GPIO22 (D4), SCL = GPIO23 (D5)
 * Motor    : GPIO0  (D0) -> 1k resistor -> NPN transistor base
 * Cal btn  : GPIO1  (D1) -> pushbutton -> GND   (internal pull-up, active LOW)
 *
 * Arduino setup:
 *   - Board package : "esp32" by Espressif, version 3.0.5 or newer
 *   - Board         : "XIAO_ESP32C6"
 *   - USB CDC On Boot: Enabled
 *   - Put this file inside a folder named BioSpine_XIAO_C6
 *
 * Connectivity: BLE GATT (primary) + USB Serial. Wi-Fi AP/WebSocket is optional
 * and OFF by default because Wi-Fi and BLE share one 2.4 GHz radio, and running
 * both is the most common reason for a weak / dropping BLE link.
 */

#include <Wire.h>
#include <Preferences.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

// ==========================================================
// BUILD OPTIONS
// ==========================================================
#define ENABLE_WIFI_AP        0     // 1 = also start Wi-Fi AP + WebSocket (port 81). Weakens BLE.
#define USE_EXTERNAL_ANTENNA  0     // 1 = use U.FL antenna (must be attached!), 0 = onboard antenna
#define BLE_TX_POWER          ESP_PWR_LVL_P9   // maximum widely supported BLE TX power (+9 dBm)

#if ENABLE_WIFI_AP
  #include <WiFi.h>
  #include <WebSocketsServer.h>
#endif

// ==========================================================
// PIN DEFINITIONS (XIAO ESP32-C6)
// ==========================================================
#define SDA_PIN               22    // D4
#define SCL_PIN               23    // D5
#define MOTOR_PIN             0     // D0
#define CAL_BTN_PIN           1     // D1
#define RF_SWITCH_ENABLE_PIN  3     // board RF switch power (LOW = on)  - do not reuse
#define RF_ANT_SELECT_PIN     14    // LOW = onboard antenna, HIGH = external - do not reuse

#ifdef LED_BUILTIN
  #define STATUS_LED_PIN      LED_BUILTIN   // GPIO15, active LOW on XIAO ESP32-C6
  #define LED_ON              LOW
  #define LED_OFF             HIGH
#endif

// ==========================================================
// MPU-6050 REGISTERS
// ==========================================================
#define MPU_REG_SMPLRT_DIV    0x19
#define MPU_REG_CONFIG        0x1A
#define MPU_REG_ACCEL_CONFIG  0x1C
#define MPU_REG_ACCEL_XOUT    0x3B
#define MPU_REG_PWR_MGMT      0x6B

// ==========================================================
// BLE UUIDs (unchanged, so the existing web app still connects)
// ==========================================================
#define SERVICE_UUID  "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define CHAR_UUID     "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define CMD_UUID      "7b9e1001-4b8a-4c18-9f21-0c2e8a8c1001"
#define BLE_NAME      "BioSpine-Wearable"
#define BLE_MTU       247           // payload per notification = MTU - 3 = 244 bytes

#if ENABLE_WIFI_AP
const char* WIFI_SSID     = "BioSpine-ESP32";
const char* WIFI_PASSWORD = "biospine123";
WebSocketsServer ws(81);
#endif

// ==========================================================
// GLOBAL STATE
// ==========================================================
Preferences prefs;

BLEServer*         pBleServer     = nullptr;
BLECharacteristic* pTelemetryChar = nullptr;
BLECharacteristic* pCmdChar       = nullptr;

volatile bool      bleConnected   = false;
volatile bool      needAdvRestart = false;
volatile unsigned long advRestartAt   = 0;

// Commands from BLE callbacks are queued and executed in loop(), so that the
// BLE task never touches the I2C bus or blocks while loop() is using it.
#define CMD_MAX_LEN 120
QueueHandle_t cmdQueue = nullptr;

uint8_t mpuAddr          = 0x68;
bool    mpuReady         = false;
int     mpuFailCount     = 0;
unsigned long lastMpuRetryMillis = 0;
unsigned long lastHeartbeatMillis = 0;

// Baseline & configurable limits
float baselinePitch = 0.0f;
float baselineRoll  = 0.0f;
bool  calibrated    = false;
float warningAngle  = 18.0f;
float safeZoneBand  = 3.0f;
float lateralLimit  = 12.0f;
bool  buzzerEnabled = false;

// Haptics
bool isSlouching = false;
bool isVibrating = false;
unsigned long vibDurationMs       = 2500;
unsigned long vibUntil            = 0;
unsigned long ignoreReadingsUntil = 0;
unsigned long connectMuteUntil    = 0;
const unsigned long CONNECT_MUTE_MS = 2000;

// Time hysteresis
unsigned long slouchStartTime = 0;
const unsigned long HYSTERESIS_MS = 2500;

// Telemetry
unsigned long lastSendTime = 0;
const unsigned long TELEMETRY_INTERVAL_MS = 100;   // 10 Hz

// Filtering
float smoothedPitch = 0.0f;
float smoothedRoll  = 0.0f;
bool  filterInit    = false;
float lastAcceptedPitch = 0.0f;
bool  lastAcceptedInit  = false;
const float MAX_JUMP_PER_SAMPLE = 14.0f;

// Deferred settings save (avoids flash wear while sliders are dragged)
bool settingsDirty = false;
unsigned long settingsDirtyAt = 0;

// ==========================================================
// HELPERS
// ==========================================================
bool anyClientConnected() {
  if (bleConnected) return true;
#if ENABLE_WIFI_AP
  if (ws.connectedClients() > 0) return true;
#endif
  return false;
}

void sendAll(const char* msg) {
  if (Serial) Serial.println(msg);                      // only when a USB host is attached
  if (bleConnected && pTelemetryChar) {
    pTelemetryChar->setValue((uint8_t*)msg, strlen(msg));
    pTelemetryChar->notify();
  }
#if ENABLE_WIFI_AP
  if (ws.connectedClients() > 0) ws.broadcastTXT(msg);
#endif
}

void enqueueCommand(const char* data, size_t len) {
  if (!cmdQueue || len == 0) return;
  char buf[CMD_MAX_LEN];
  size_t n = (len < CMD_MAX_LEN - 1) ? len : (CMD_MAX_LEN - 1);
  memcpy(buf, data, n);
  buf[n] = 0;
  xQueueSend(cmdQueue, buf, 0);
}

void setupAntenna() {
  pinMode(RF_SWITCH_ENABLE_PIN, OUTPUT);
  digitalWrite(RF_SWITCH_ENABLE_PIN, LOW);     // power the RF switch
  delay(10);
  pinMode(RF_ANT_SELECT_PIN, OUTPUT);
  digitalWrite(RF_ANT_SELECT_PIN, USE_EXTERNAL_ANTENNA ? HIGH : LOW);
}

// ==========================================================
// MOTOR
// ==========================================================
void motorOff() {
  digitalWrite(MOTOR_PIN, LOW);
  isVibrating = false;
  vibUntil = 0;
}

void triggerPulse(unsigned long durationMs) {
  if (!buzzerEnabled || millis() < connectMuteUntil) {
    motorOff();
    return;
  }
  digitalWrite(MOTOR_PIN, HIGH);
  isVibrating = true;
  vibUntil = millis() + durationMs;
  ignoreReadingsUntil = millis() + durationMs + 200;   // ignore motor noise on the sensor
}

// ==========================================================
// MPU-6050 ACCESS
// ==========================================================
bool mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(mpuAddr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

bool mpuInit() {
  // AD0 low -> 0x68, AD0 high -> 0x69. Try both.
  const uint8_t addrs[2] = {0x68, 0x69};
  bool found = false;
  for (uint8_t i = 0; i < 2; i++) {
    Wire.beginTransmission(addrs[i]);
    if (Wire.endTransmission() == 0) { mpuAddr = addrs[i]; found = true; break; }
  }
  if (!found) return false;

  if (!mpuWrite(MPU_REG_PWR_MGMT, 0x00)) return false;   // wake from sleep
  delay(50);
  mpuWrite(MPU_REG_SMPLRT_DIV, 9);        // 100 Hz internal sample rate
  mpuWrite(MPU_REG_CONFIG, 0x03);         // digital low-pass ~44 Hz
  mpuWrite(MPU_REG_ACCEL_CONFIG, 0x00);   // +/-2 g (16384 LSB/g)
  mpuFailCount = 0;
  return true;
}

void mpuMarkFailure() {
  mpuFailCount++;
  if (mpuFailCount > 25) {
    // Sensor stopped answering: drop to "not ready" so the retry + heartbeat path takes over.
    mpuReady = false;
    mpuFailCount = 0;
    filterInit = false;
    lastAcceptedInit = false;
  }
}

bool readRawSensor(float &rawPitch, float &rawRoll, bool &isMotionGlitch) {
  Wire.beginTransmission(mpuAddr);
  Wire.write(MPU_REG_ACCEL_XOUT);
  if (Wire.endTransmission(false) != 0) { mpuMarkFailure(); return false; }

  if (Wire.requestFrom((uint8_t)mpuAddr, (size_t)6, true) != 6) { mpuMarkFailure(); return false; }

  uint8_t b[6];
  for (int i = 0; i < 6; i++) b[i] = Wire.read();
  int16_t axRaw = (int16_t)((b[0] << 8) | b[1]);
  int16_t ayRaw = (int16_t)((b[2] << 8) | b[3]);
  int16_t azRaw = (int16_t)((b[4] << 8) | b[5]);

  float ax = axRaw / 16384.0f;
  float ay = ayRaw / 16384.0f;
  float az = azRaw / 16384.0f;

  float totalAcc = sqrtf(ax * ax + ay * ay + az * az);
  if (totalAcc < 0.5f) { mpuMarkFailure(); return false; }   // all-zero / dead readings

  mpuFailCount = 0;
  isMotionGlitch = (fabsf(totalAcc - 1.0f) > 0.20f);

  // Mirrored: Forward <-> Backward and Left <-> Right inverted
  rawPitch = -(atan2f(-ax, az) * 180.0f / PI);
  rawRoll  = -(atan2f(ay, sqrtf(ax * ax + az * az)) * 180.0f / PI);
  return true;
}

bool getFilteredKinematics(float &pitchOut, float &rollOut, bool &isGlitch) {
  if (!mpuReady) return false;

  float pRaw, rRaw;
  isGlitch = false;
  if (!readRawSensor(pRaw, rRaw, isGlitch)) return false;

  if (lastAcceptedInit) {
    float jump = pRaw - lastAcceptedPitch;
    if (jump > MAX_JUMP_PER_SAMPLE)       pRaw = lastAcceptedPitch + MAX_JUMP_PER_SAMPLE;
    else if (jump < -MAX_JUMP_PER_SAMPLE) pRaw = lastAcceptedPitch - MAX_JUMP_PER_SAMPLE;
  }
  lastAcceptedPitch = pRaw;
  lastAcceptedInit  = true;

  if (!filterInit) {
    smoothedPitch = pRaw;
    smoothedRoll  = rRaw;
    filterInit    = true;
  } else if (!isGlitch && millis() >= ignoreReadingsUntil) {
    smoothedPitch = (0.15f * pRaw) + (0.85f * smoothedPitch);
    smoothedRoll  = (0.15f * rRaw) + (0.85f * smoothedRoll);
  }

  pitchOut = smoothedPitch;
  rollOut  = smoothedRoll;
  return true;
}

// ==========================================================
// SETTINGS (NVS)
// ==========================================================
void saveSettings() {
  prefs.putFloat("warnA", warningAngle);
  prefs.putFloat("safeZ", safeZoneBand);
  prefs.putFloat("latL",  lateralLimit);
  prefs.putBool("buzzOn", buzzerEnabled);
  prefs.putULong("vibMs", vibDurationMs);
}

void markSettingsDirty() {
  settingsDirty = true;
  settingsDirtyAt = millis();
}

// ==========================================================
// CALIBRATION
// ==========================================================
void calibrate() {
  motorOff();
  Serial.println("[BioSpine] Calibrating...");

  filterInit = false;
  lastAcceptedInit = false;
  ignoreReadingsUntil = 0;

  float sumP = 0.0f, sumR = 0.0f;
  int valid = 0;
  for (int i = 0; i < 30; i++) {
    float p, r; bool glitch;
    if (getFilteredKinematics(p, r, glitch) && !glitch) {
      sumP += p; sumR += r; valid++;
    }
    delay(20);
  }

  if (valid >= 10) {
    baselinePitch = sumP / valid;
    baselineRoll  = sumR / valid;
    calibrated = true;
    prefs.putFloat("baseP", baselinePitch);
    prefs.putFloat("baseR", baselineRoll);
    prefs.putBool("cal", true);
    isSlouching = false;
    slouchStartTime = 0;

    if (buzzerEnabled) {   // double micro-pulse confirmation
      digitalWrite(MOTOR_PIN, HIGH); delay(80);
      digitalWrite(MOTOR_PIN, LOW);  delay(80);
      digitalWrite(MOTOR_PIN, HIGH); delay(80);
      digitalWrite(MOTOR_PIN, LOW);
    }
    Serial.printf("[BioSpine] Baseline: Pitch=%.1f Roll=%.1f\n", baselinePitch, baselineRoll);
  } else {
    Serial.println("[BioSpine] Calibration failed (sensor not steady). Hold still and retry.");
  }
}

// ==========================================================
// TELEMETRY
// ==========================================================
void broadcastTelemetry(float absPitch, float pitchDev, float absRoll, float rollDev, bool slouchState) {
  char payload[200];
  snprintf(payload, sizeof(payload),
    "{\"dev\":%.1f,\"signedDev\":%.1f,\"pitch\":%.1f,"
    "\"rollDev\":%.1f,\"signedRoll\":%.1f,"
    "\"slouch\":%s,\"vib\":%s,\"calibrated\":%s,\"mpu\":\"%s\"}",
    absPitch, pitchDev, smoothedPitch,
    absRoll, rollDev,
    slouchState ? "true" : "false",
    isVibrating ? "true" : "false",
    calibrated ? "true" : "false",
    mpuReady ? "ok" : "err");
  sendAll(payload);
}

// ==========================================================
// COMMANDS (BLE / USB Serial / WebSocket) - executed from loop()
// ==========================================================
bool jsonNumber(const String &s, const char *key, float &out) {
  String k = String("\"") + key + "\"";
  int p = s.indexOf(k);
  if (p < 0) return false;
  int c = s.indexOf(':', p + k.length());
  if (c < 0) return false;
  String v = s.substring(c + 1);
  v.trim();
  if (v.startsWith("\"")) v.remove(0, 1);
  out = v.toFloat();
  return true;
}

void processCommand(const String &cmd) {
  Serial.print("[BioSpine] Command: ");
  Serial.println(cmd);

  if (cmd.indexOf("calibrate\"") >= 0) calibrate();
  if (cmd.indexOf("\"buzz\"") >= 0)    triggerPulse(300);

  float v;
  if (jsonNumber(cmd, "angle", v))        { warningAngle = constrain(v, 3.0f, 60.0f);  markSettingsDirty(); }
  if (jsonNumber(cmd, "safeZone", v))     { safeZoneBand = constrain(v, 0.0f, 15.0f);  markSettingsDirty(); }
  if (jsonNumber(cmd, "lateralLimit", v)) { lateralLimit = constrain(v, 3.0f, 60.0f);  markSettingsDirty(); }
  if (jsonNumber(cmd, "buzzDuration", v)) {
    unsigned long ms = (v < 20.0f) ? (unsigned long)(v * 1000.0f) : (unsigned long)v;
    vibDurationMs = constrain(ms, 100UL, 10000UL);
    markSettingsDirty();
  }

  int p = cmd.indexOf("\"buzzerEnabled\"");
  if (p >= 0) {
    int colon = cmd.indexOf(':', p);
    if (colon >= 0) {
      buzzerEnabled = (cmd.substring(colon + 1).indexOf("true") >= 0);
      if (!buzzerEnabled) motorOff();
      markSettingsDirty();
    }
  }
}

// ==========================================================
// BLE CALLBACKS  (keep them tiny: no I2C, no delay, no long work)
// ==========================================================
class BleServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *s) override {
    bleConnected = true;
    needAdvRestart = false;
    connectMuteUntil = millis() + CONNECT_MUTE_MS;
    motorOff();
  }
  void onDisconnect(BLEServer *s) override {
    bleConnected = false;
    motorOff();
    needAdvRestart = true;               // restarted from loop()
    advRestartAt = millis() + 300;
  }
};

class BleCommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *pChar) override {
    String val = pChar->getValue().c_str();
    if (val.length() > 0) enqueueCommand(val.c_str(), val.length());
  }
};

// ==========================================================
// WI-FI WEBSOCKET (optional)
// ==========================================================
#if ENABLE_WIFI_AP
void webSocketEvent(uint8_t clientNum, WStype_t type, uint8_t *payload, size_t length) {
  if (type == WStype_CONNECTED) {
    connectMuteUntil = millis() + CONNECT_MUTE_MS;
    motorOff();
  } else if (type == WStype_DISCONNECTED) {
    if (ws.connectedClients() == 0) motorOff();
  } else if (type == WStype_TEXT) {
    enqueueCommand((const char*)payload, length);
  }
}
#endif

// ==========================================================
// BLE SETUP
// ==========================================================
void setupBle() {
  BLEDevice::init(BLE_NAME);
  BLEDevice::setMTU(BLE_MTU);
  BLEDevice::setPower(BLE_TX_POWER);                       // connection / default
  BLEDevice::setPower(BLE_TX_POWER, ESP_BLE_PWR_TYPE_ADV); // advertising (range for first contact)

  pBleServer = BLEDevice::createServer();
  pBleServer->setCallbacks(new BleServerCallbacks());

  BLEService *pService = pBleServer->createService(SERVICE_UUID);

  pTelemetryChar = pService->createCharacteristic(
    CHAR_UUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  pTelemetryChar->addDescriptor(new BLE2902());

  pCmdChar = pService->createCharacteristic(
    CMD_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  pCmdChar->setCallbacks(new BleCommandCallbacks());

  pService->start();

  BLEAdvertising *pAdv = BLEDevice::getAdvertising();
  pAdv->addServiceUUID(SERVICE_UUID);
  pAdv->setScanResponse(true);          // device name goes in the scan response
  pAdv->setMinInterval(0x20);           // 20 ms
  pAdv->setMaxInterval(0x40);           // 40 ms  -> fast discovery and reconnect
  pAdv->setMinPreferred(0x06);          // helps iOS / Android connect quickly
  pAdv->setMaxPreferred(0x12);
  BLEDevice::startAdvertising();
}

// ==========================================================
// STATUS LED  (solid = client connected, slow blink = advertising, fast blink = sensor error)
// ==========================================================
void updateStatusLed() {
#ifdef STATUS_LED_PIN
  static unsigned long last = 0;
  static bool state = false;
  if (mpuReady && anyClientConnected()) { digitalWrite(STATUS_LED_PIN, LED_ON); return; }
  unsigned long interval = mpuReady ? 600 : 150;
  if (millis() - last >= interval) {
    last = millis();
    state = !state;
    digitalWrite(STATUS_LED_PIN, state ? LED_ON : LED_OFF);
  }
#endif
}

// ==========================================================
// SETUP
// ==========================================================
void setup() {
  Serial.begin(115200);
#if ARDUINO_USB_CDC_ON_BOOT
  Serial.setTxTimeoutMs(0);   // never block when no USB host is reading
#endif
  Serial.setTimeout(20);
  delay(200);

  pinMode(MOTOR_PIN, OUTPUT);
  motorOff();

  pinMode(CAL_BTN_PIN, INPUT_PULLUP);
#ifdef STATUS_LED_PIN
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LED_OFF);
#endif

  setupAntenna();                       // must happen before the radio starts

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);
  Wire.setTimeOut(50);                  // ms; prevents the I2C bus from hanging the loop
  delay(100);                           // MPU-6050 power-up time
  mpuReady = mpuInit();
  Serial.printf("[BioSpine] MPU ready: %s (addr 0x%02X)\n", mpuReady ? "YES" : "NO", mpuAddr);

  prefs.begin("biospine", false);
  baselinePitch = prefs.getFloat("baseP", 0.0f);
  baselineRoll  = prefs.getFloat("baseR", 0.0f);
  calibrated    = prefs.getBool("cal", false);
  warningAngle  = prefs.getFloat("warnA", warningAngle);
  safeZoneBand  = prefs.getFloat("safeZ", safeZoneBand);
  lateralLimit  = prefs.getFloat("latL",  lateralLimit);
  buzzerEnabled = prefs.getBool("buzzOn", buzzerEnabled);
  vibDurationMs = prefs.getULong("vibMs", vibDurationMs);

  cmdQueue = xQueueCreate(8, CMD_MAX_LEN);

#if ENABLE_WIFI_AP
  WiFi.mode(WIFI_AP);
  WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
  ws.begin();
  ws.onEvent(webSocketEvent);
#endif

  setupBle();

  Serial.println("==================================================");
  Serial.println(" BioSpine BLE firmware ready (XIAO ESP32-C6)");
  Serial.printf(" Antenna: %s | Wi-Fi AP: %s\n",
                USE_EXTERNAL_ANTENNA ? "external" : "onboard",
                ENABLE_WIFI_AP ? "on" : "off");
  Serial.println("==================================================");
}

// ==========================================================
// LOOP
// ==========================================================
void loop() {
#if ENABLE_WIFI_AP
  ws.loop();
#endif

  // Commands queued by BLE / WebSocket
  char cmdBuf[CMD_MAX_LEN];
  while (cmdQueue && xQueueReceive(cmdQueue, cmdBuf, 0) == pdTRUE) {
    processCommand(String(cmdBuf));
  }

  // USB serial commands
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.startsWith("{")) processCommand(line);
  }

  // Calibration button (debounced, triggers once per press)
  {
    static bool lastRaw = HIGH, stable = HIGH;
    static unsigned long changedAt = 0;
    bool raw = digitalRead(CAL_BTN_PIN);
    if (raw != lastRaw) { lastRaw = raw; changedAt = millis(); }
    if (millis() - changedAt > 40 && raw != stable) {
      stable = raw;
      if (stable == LOW) calibrate();
    }
  }

  // Non-blocking motor timeout
  if (isVibrating && millis() >= vibUntil) motorOff();

  // Restart BLE advertising after a disconnect
  if (needAdvRestart && millis() >= advRestartAt) {
    needAdvRestart = false;
    BLEDevice::startAdvertising();
  }

  // Deferred settings save
  if (settingsDirty && millis() - settingsDirtyAt > 2000) {
    settingsDirty = false;
    saveSettings();
  }

  // Sensor recovery + heartbeat so the app can show "sensor not detected"
  if (!mpuReady && millis() - lastMpuRetryMillis >= 2000) {
    lastMpuRetryMillis = millis();
    mpuReady = mpuInit();
    if (mpuReady) Serial.println("[BioSpine] MPU6050 online.");
  }
  if (!mpuReady && millis() - lastHeartbeatMillis >= 1000) {
    lastHeartbeatMillis = millis();
    sendAll("{\"mpu\":\"err\",\"sensorOk\":false,\"heartbeat\":true}");
  }

  // Sensing
  float p, r;
  bool isGlitch = false;
  if (getFilteredKinematics(p, r, isGlitch)) {
    float pitchDev = p - baselinePitch;
    float rollDev  = r - baselineRoll;
    float absPitch = fabsf(pitchDev);
    float absRoll  = fabsf(rollDev);

    // While the user is moving (glitch) hold the current state instead of flipping it.
    if (!isGlitch) {
      float pThresh = isSlouching ? (warningAngle - safeZoneBand) : (warningAngle + safeZoneBand);
      float rThresh = isSlouching ? (lateralLimit - safeZoneBand) : (lateralLimit + safeZoneBand);
      bool exceeds = (absPitch > pThresh) || (absRoll > rThresh);

      if (exceeds) {
        if (slouchStartTime == 0) slouchStartTime = millis();
        if (!isSlouching && millis() - slouchStartTime >= HYSTERESIS_MS) {
          isSlouching = true;
          triggerPulse(vibDurationMs);
          broadcastTelemetry(absPitch, pitchDev, absRoll, rollDev, true);
        }
      } else {
        slouchStartTime = 0;
        if (isSlouching) {
          isSlouching = false;
          motorOff();
          broadcastTelemetry(absPitch, pitchDev, absRoll, rollDev, false);
        }
      }
    }

    if (millis() - lastSendTime >= TELEMETRY_INTERVAL_MS) {
      lastSendTime = millis();
      broadcastTelemetry(absPitch, pitchDev, absRoll, rollDev, isSlouching);
    }
  }

  updateStatusLed();
  delay(5);
}