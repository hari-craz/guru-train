#pragma once
// ---------- WI-FI: the ESP32 creates its own network (access point) ----------
// Connect the laptop to this Wi-Fi, run the Flask site, and it links up automatically:
// the server connects to ws://192.168.4.1:81
#define AP_SSID        "SmartRail-ESP32"
#define AP_PASSWORD    "smartrail123"     // at least 8 characters
#define WS_PORT        81

// ---------- PIN MAP (ESP32 DevKit V1, 30-pin) ----------
// RC522 (VSPI)      SDA/SS=5  SCK=18  MOSI=23  MISO=19  RST=4  3.3V  GND
#define PIN_RC522_SS   5
#define PIN_RC522_RST  4    // moved off GPIO22 because that pin is I2C SCL for the LCD
// IR sensors (TCRT5000 modules, OUT pin). GPIO34/35 are input-only - perfect here.
#define PIN_IR1        34   // before the switch  (approach / entry)
#define PIN_IR2        35   // after the merge    (exit / clear)
#define IR_ACTIVE_LEVEL LOW // these modules pull OUT low when an object is seen
// Servo (track switch)
#define PIN_SERVO      13
#define SERVO_MAIN_DEG 30
#define SERVO_LOOP_DEG 110
// LCD 16x2 with I2C backpack: SDA = GPIO21, SCL = GPIO22 (ESP32 default I2C pins)
#define LCD_I2C_ADDR 0x27   // some backpacks use 0x3F - run an I2C scanner if the LCD stays blank
