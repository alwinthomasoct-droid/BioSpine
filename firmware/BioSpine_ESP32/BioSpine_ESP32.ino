#include <Wire.h>
#include <WiFi.h>
#include <WebSocketsServer.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Preferences.h>

#define SDA_PIN             21
#define SCL_PIN             22
#define MOTOR_PIN           4
#define CAL_BTN_PIN         18

// ---------------------------------------------------------------------------
// SENSOR DIRECTIONS (v5.5)
// The app showed FORWARD lean as LEFT, LEFT as FORWARD, BACK as RIGHT and RIGHT as BACK:
// the chip sits turned 90 degrees on the neck, so its two tilt axes were swapped.
// With AXES_TURNED_90 = 1 the axes are swapped back, so that
//     lean FORWARD -> pitch +     lean BACKWARD -> pitch -
//     lean RIGHT   -> roll  +     lean LEFT     -> roll  -
// The buzzing rules (forward limit / sideways limit) now use the correct directions too.
// If you ever mount the chip the other way round, set this to 0.
// After flashing, press the calibrate button once (or "Set my good posture" in the app).
// ---------------------------------------------------------------------------
#define AXES_TURNED_90      1
#define AXES_VERSION        2    // changing the mounting makes the saved good-posture values invalid, so they are cleared once

#define MPU_ADDR            0x68
#define MPU_REG_PWR_MGMT    0x6B
#define MPU_REG_ACCEL_XOUT  0x3B

#define SERVICE_UUID        "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define CHAR_UUID           "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define CMD_UUID            "7b9e1001-4b8a-4c18-9f21-0c2e8a8c1001"

const char* WIFI_SSID     = "BioSpine-ESP32";
const char* WIFI_PASSWORD = "biospine123";

Preferences prefs;
WebSocketsServer wsServer(81);
BLEServer* pBleServer = nullptr;
BLECharacteristic* pTelemetryChar = nullptr;
BLECharacteristic* pCmdChar = nullptr;

bool bleConnected = false;
bool wsConnected = false;
bool mpuReady = false;
unsigned long lastMpuRetryMillis = 0;
unsigned long lastHeartbeatMillis = 0;

float baselinePitch = 0.0f;
float baselineRoll  = 0.0f;
float warningAngle = 18.0f;
float safeZoneBand = 3.0f;
float lateralLimit = 12.0f;
bool buzzerEnabled = true;

bool confirmedSlouch = false;
unsigned long slouchStartTime = 0;
const unsigned long HYSTERESIS_DELAY_MS = 3000;

unsigned long lastPulseToggle = 0;
bool pulseState = false;
unsigned long lastTelemetryMillis = 0;
float smoothedPitch = 0.0f;
float smoothedRoll  = 0.0f;
bool filterInit = false;

void writeI2C(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

bool initSensor() {
  Wire.beginTransmission(MPU_ADDR);
  if (Wire.endTransmission() != 0) return false;
  writeI2C(MPU_REG_PWR_MGMT, 0x00);
  delay(30);
  return true;
}

bool readRawKinematics(float &outPitch, float &outRoll, bool &isMotionGlitch) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(MPU_REG_ACCEL_XOUT);
  if (Wire.endTransmission(false) != 0) return false;

  Wire.requestFrom((uint8_t)MPU_ADDR, (size_t)6, true);
  if (Wire.available() < 6) return false;

  int16_t axRaw = (Wire.read() << 8) | Wire.read();
  int16_t ayRaw = (Wire.read() << 8) | Wire.read();
  int16_t azRaw = (Wire.read() << 8) | Wire.read();

  float ax_g = axRaw / 16384.0f;
  float ay_g = ayRaw / 16384.0f;
  float az_g = azRaw / 16384.0f;

  float totalAcc = sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g);
  isMotionGlitch = (fabs(totalAcc - 1.0f) > 0.20f);

  float rawPitch = atan2(ay_g, sqrt(ax_g * ax_g + az_g * az_g)) * 180.0f / PI;
  float rawRoll  = atan2(-ax_g, az_g) * 180.0f / PI;
#if AXES_TURNED_90
  outPitch = -rawRoll;     // forward / backward
  outRoll  = -rawPitch;    // left / right
#else
  outPitch = rawPitch;
  outRoll  = rawRoll;
#endif
  return true;
}

void motorStop() {
  digitalWrite(MOTOR_PIN, LOW);
  pulseState = false;
}

void updateHapticActuation() {
  if (!buzzerEnabled || !confirmedSlouch) {
    motorStop();
    return;
  }
  unsigned long now = millis();
  if (pulseState && (now - lastPulseToggle >= 250)) {
    digitalWrite(MOTOR_PIN, LOW);
    pulseState = false;
    lastPulseToggle = now;
  } else if (!pulseState && (now - lastPulseToggle >= 150)) {
    digitalWrite(MOTOR_PIN, HIGH);
    pulseState = true;
    lastPulseToggle = now;
  }
}

void calibrateZeroBaseline() {
  motorStop();
  float accP = 0.0f, accR = 0.0f;
  int count = 0;
  for (int i = 0; i < 30; i++) {
    float p, r; bool motion;
    if (readRawKinematics(p, r, motion) && !motion) {
      accP += p; accR += r; count++;
    }
    delay(20);
  }
  if (count > 0) {
    baselinePitch = accP / count;
    baselineRoll  = accR / count;
    prefs.putFloat("baseP", baselinePitch);
    prefs.putFloat("baseR", baselineRoll);
    confirmedSlouch = false;
    digitalWrite(MOTOR_PIN, HIGH); delay(80);
    digitalWrite(MOTOR_PIN, LOW);  delay(100);
    digitalWrite(MOTOR_PIN, HIGH); delay(80);
    digitalWrite(MOTOR_PIN, LOW);
  }
}

void processCommand(String json) {
  if (json.indexOf("calibrate") >= 0) calibrateZeroBaseline();
  if (json.indexOf("\"buzz\"") >= 0) {
    digitalWrite(MOTOR_PIN, HIGH); delay(250); digitalWrite(MOTOR_PIN, LOW);
  }
  int p = json.indexOf("angle");
  if (p >= 0) {
    int c = json.indexOf(':', p);
    if (c >= 0) warningAngle = json.substring(c + 1).toFloat();
  }
  p = json.indexOf("safeZone");
  if (p >= 0) {
    int c = json.indexOf(':', p);
    if (c >= 0) safeZoneBand = json.substring(c + 1).toFloat();
  }
  p = json.indexOf("lateralLimit");
  if (p >= 0) {
    int c = json.indexOf(':', p);
    if (c >= 0) lateralLimit = json.substring(c + 1).toFloat();
  }
  p = json.indexOf("buzzerEnabled");
  if (p >= 0) {
    int c = json.indexOf(':', p);
    if (c >= 0) buzzerEnabled = (json.substring(c + 1).indexOf("true") >= 0);
  }
}

class BleServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* s) override {
    bleConnected = true;
    motorStop();
  }
  void onDisconnect(BLEServer* s) override {
    bleConnected = false;
    motorStop();
    BLEDevice::startAdvertising();
  }
};

class BleCommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* pChar) override {
    String val = pChar->getValue().c_str();
    if (val.length() > 0) processCommand(val);
  }
};

void onWsEvent(uint8_t clientNum, WStype_t type, uint8_t *payload, size_t length) {
  if (type == WStype_CONNECTED) {
    wsConnected = true;
    motorStop();
  } else if (type == WStype_DISCONNECTED) {
    wsConnected = false;
    motorStop();
  } else if (type == WStype_TEXT) {
    processCommand(String((char*)payload));
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_PIN, OUTPUT);
  motorStop();
  pinMode(CAL_BTN_PIN, INPUT_PULLDOWN);

  Wire.begin(SDA_PIN, SCL_PIN);
  mpuReady = initSensor();

  prefs.begin("biospine", false);
  baselinePitch = prefs.getFloat("baseP", 0.0f);
  baselineRoll  = prefs.getFloat("baseR", 0.0f);
  if (prefs.getInt("axesVer", 0) != AXES_VERSION) {      // the saved values were measured with the old axes: start fresh
    baselinePitch = 0.0f;
    baselineRoll  = 0.0f;
    prefs.putFloat("baseP", 0.0f);
    prefs.putFloat("baseR", 0.0f);
    prefs.putInt("axesVer", AXES_VERSION);
  }

  WiFi.mode(WIFI_AP);
  WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
  wsServer.begin();
  wsServer.onEvent(onWsEvent);

  BLEDevice::init("BioSpine-Wearable");
  BLEDevice::setMTU(517);   // allow the full JSON telemetry packet in one BLE notification (default MTU 23 truncates it)
  pBleServer = BLEDevice::createServer();
  pBleServer->setCallbacks(new BleServerCallbacks());

  BLEService* pService = pBleServer->createService(SERVICE_UUID);
  pTelemetryChar = pService->createCharacteristic(CHAR_UUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  pTelemetryChar->addDescriptor(new BLE2902());
  pCmdChar = pService->createCharacteristic(CMD_UUID, BLECharacteristic::PROPERTY_WRITE);
  pCmdChar->setCallbacks(new BleCommandCallbacks());
  pService->start();

  BLEAdvertising* pAdv = BLEDevice::getAdvertising();
  pAdv->addServiceUUID(SERVICE_UUID);
  pAdv->setScanResponse(true);
  BLEDevice::startAdvertising();
}

void loop() {
  wsServer.loop();
  if (digitalRead(CAL_BTN_PIN) == HIGH) calibrateZeroBaseline();
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.startsWith("{")) processCommand(line);
  }

  // *** FIX: the sensor is only probed once, in setup(). If the MPU6050 isn't
  // ready yet at power-on (common: it powers up a few ms slower than the
  // ESP32, or AD0 is wired to the wrong level so it answers on 0x69 instead
  // of 0x68), mpuReady latches false FOREVER and the block below - which is
  // the only place that sends BLE notifications - never runs again. That is
  // exactly "BLE connects, but no data ever arrives". Retrying periodically
  // means a device that was just slow to boot recovers on its own instead of
  // needing a manual reset.
  if (!mpuReady && millis() - lastMpuRetryMillis >= 2000) {
    lastMpuRetryMillis = millis();
    mpuReady = initSensor();
    if (mpuReady) Serial.println("[BioSpine] MPU6050 came online on retry.");
  }

  // Heartbeat: sent once a second over BLE/Wi-Fi even while the sensor is
  // still missing, so the web app can show "connected, but sensor not
  // detected" instead of looking silently dead - this is the #1 symptom
  // reported as "Bluetooth connects but no data transfers".
  if (!mpuReady && millis() - lastHeartbeatMillis >= 1000) {
    lastHeartbeatMillis = millis();
    char hb[64];
    snprintf(hb, sizeof(hb), "{\"sensorOk\":false,\"heartbeat\":true}");
    Serial.println(hb);
    if (bleConnected && pTelemetryChar) {
      pTelemetryChar->setValue(hb);
      pTelemetryChar->notify();
    }
    if (wsConnected) wsServer.broadcastTXT(hb);
  }

  float rawP, rawR; bool isMoving;
  if (mpuReady && readRawKinematics(rawP, rawR, isMoving)) {
    if (!filterInit) {
      smoothedPitch = rawP; smoothedRoll = rawR; filterInit = true;
    } else if (!isMoving) {
      smoothedPitch = (0.15f * rawP) + (0.85f * smoothedPitch);
      smoothedRoll  = (0.15f * rawR) + (0.85f * smoothedRoll);
    }

    float pitchDev = smoothedPitch - baselinePitch;
    float rollDev  = smoothedRoll  - baselineRoll;
    float absPitch = fabs(pitchDev);
    float absRoll  = fabs(rollDev);

    float pitchThreshold = confirmedSlouch ? (warningAngle - safeZoneBand) : (warningAngle + safeZoneBand);
    float rollThreshold  = confirmedSlouch ? (lateralLimit - safeZoneBand) : (lateralLimit + safeZoneBand);
    bool exceedsTolerance = ((absPitch > pitchThreshold) || (absRoll > rollThreshold)) && !isMoving;

    if (exceedsTolerance) {
      if (slouchStartTime == 0) slouchStartTime = millis();
      if (millis() - slouchStartTime >= HYSTERESIS_DELAY_MS) confirmedSlouch = true;
    } else {
      slouchStartTime = 0;
      confirmedSlouch = false;
    }

    updateHapticActuation();

    if (millis() - lastTelemetryMillis >= 100) {
      lastTelemetryMillis = millis();
      char buffer[160];
      snprintf(buffer, sizeof(buffer),
        "{\"dev\":%.1f,\"signedDev\":%.1f,\"pitch\":%.1f,\"rollDev\":%.1f,\"signedRoll\":%.1f,\"slouch\":%s,\"vib\":%s}",
        absPitch, pitchDev, smoothedPitch, absRoll, rollDev,
        confirmedSlouch ? "true" : "false", pulseState ? "true" : "false");

      Serial.println(buffer);
      if (bleConnected && pTelemetryChar) {
        pTelemetryChar->setValue(buffer);
        pTelemetryChar->notify();
      }
      if (wsConnected) {
        wsServer.broadcastTXT(buffer);
      }
    }
  }
  delay(10);
}
