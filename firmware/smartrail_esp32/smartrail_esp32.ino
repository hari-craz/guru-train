/*
  SmartRail AI - ESP32 firmware (access-point mode)
  RC522 RFID + 2x IR + SG90 servo (track switch) + 16x2 I2C LCD

  The ESP32 creates its own Wi-Fi (config.h: AP_SSID). The laptop joins it and the Flask
  server connects to ws://192.168.4.1:81, then exchanges JSON messages with this board.

  Arduino libraries (Library Manager):
    MFRC522, WebSockets (Markus Sattler), ArduinoJson (v7), ESP32Servo, LiquidCrystal_I2C
  Board: "ESP32 Dev Module"
*/
#include <WiFi.h>
#include <SPI.h>
#include <MFRC522.h>
#include <WebSocketsServer.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "config.h"

#define FW_VERSION "1.1-ap"

MFRC522 rfid(PIN_RC522_SS, PIN_RC522_RST);
WebSocketsServer wsServer(WS_PORT);
Servo gate;
LiquidCrystal_I2C lcd(LCD_I2C_ADDR, 16, 2);

int clients = 0;
String curPos = "MAIN";
bool ir1Last = false, ir2Last = false;
unsigned long ir1T = 0, ir2T = 0, lastScanT = 0;
String lastUid = "";
byte rcVersion = 0;

// ---------- helpers ----------
void showLcd(const String &a, const String &b) {
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print(a.substring(0, 16));
  lcd.setCursor(0, 1); lcd.print(b.substring(0, 16));
}

void sendJson(JsonDocument &doc) {
  if (clients <= 0) return;
  String out;
  serializeJson(doc, out);
  wsServer.broadcastTXT(out);
}

void setSwitch(const String &pos, bool ack) {
  curPos = pos;
  gate.write(pos == "LOOP" ? SERVO_LOOP_DEG : SERVO_MAIN_DEG);
  if (ack) {
    JsonDocument d;
    d["type"] = "switch_ack"; d["pos"] = pos;
    sendJson(d);
  }
}

// ---------- websocket server ----------
void onWs(uint8_t num, WStype_t type, uint8_t *payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED: {
      clients++;
      JsonDocument d;
      d["type"] = "hello"; d["fw"] = FW_VERSION;
      d["rc522"] = String(rcVersion, HEX);
      String out; serializeJson(d, out);
      wsServer.sendTXT(num, out);
      break;
    }
    case WStype_DISCONNECTED:
      if (clients > 0) clients--;
      if (clients == 0) showLcd("SERVER OFFLINE", "AUTO FALLBACK");
      break;
    case WStype_TEXT: {
      JsonDocument d;
      if (deserializeJson(d, payload, len)) return;
      const char *t = d["type"];
      if (!t) return;
      if (!strcmp(t, "switch")) setSwitch(String((const char *)d["pos"]), true);
      else if (!strcmp(t, "lcd")) showLcd(String((const char *)d["l1"]), String((const char *)d["l2"]));
      break;
    }
    default: break;
  }
}

void sendIr(int sensor, bool on) {
  JsonDocument d;
  d["type"] = "ir"; d["sensor"] = sensor; d["state"] = on;
  sendJson(d);
}

// ---------- setup / loop ----------
void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  showLcd("SMARTRAIL AI", "BOOTING...");

  pinMode(PIN_IR1, INPUT);
  pinMode(PIN_IR2, INPUT);

  ESP32PWM::allocateTimer(0);
  gate.setPeriodHertz(50);
  gate.attach(PIN_SERVO, 500, 2400);
  setSwitch("MAIN", false);

  SPI.begin();            // SCK18 MISO19 MOSI23
  rfid.PCD_Init();
  rcVersion = rfid.PCD_ReadRegister(MFRC522::VersionReg);   // 0x91/0x92 = genuine RC522; 0x00/0xFF = wiring problem
  bool rcOk = (rcVersion != 0x00 && rcVersion != 0xFF);   // clones report 0x82, 0x88, 0x12 ...
  Serial.print("RC522 version 0x"); Serial.println(rcVersion, HEX);
  showLcd(rcOk ? "RC522 OK" : "RC522 NOT FOUND", "ver 0x" + String(rcVersion, HEX));
  delay(2500);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASSWORD);
  Serial.print("AP "); Serial.print(AP_SSID); Serial.print("  IP ");
  Serial.println(WiFi.softAPIP());
  showLcd(AP_SSID, WiFi.softAPIP().toString());

  wsServer.begin();
  wsServer.onEvent(onWs);
  wsServer.enableHeartbeat(15000, 3000, 2);
}

void loop() {
  wsServer.loop();
  unsigned long now = millis();

  // --- IR sensors with 150 ms debounce, edge-triggered
  bool i1 = digitalRead(PIN_IR1) == IR_ACTIVE_LEVEL;
  bool i2 = digitalRead(PIN_IR2) == IR_ACTIVE_LEVEL;
  if (i1 != ir1Last && now - ir1T > 150) { ir1Last = i1; ir1T = now; sendIr(1, i1); }
  if (i2 != ir2Last && now - ir2T > 150) { ir2Last = i2; ir2T = now; sendIr(2, i2); }

  // --- RFID (ignore the same tag for 2 s)
  if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
    String uid;
    for (byte i = 0; i < rfid.uid.size; i++) {
      if (rfid.uid.uidByte[i] < 0x10) uid += "0";
      uid += String(rfid.uid.uidByte[i], HEX);
    }
    uid.toUpperCase();
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    if (uid != lastUid || now - lastScanT > 2000) {
      lastUid = uid; lastScanT = now;
      Serial.println("RFID " + uid);
      if (clients > 0) {
        JsonDocument d;
        d["type"] = "rfid"; d["uid"] = uid;
        sendJson(d);
      } else {
        // Offline fallback: no server, so alternate the track and show the tag
        setSwitch(curPos == "MAIN" ? "LOOP" : "MAIN", false);
        showLcd("TAG " + uid, "ROUTE " + curPos);
      }
    }
  }
}
