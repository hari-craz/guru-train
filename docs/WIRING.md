# SmartRail AI – Wiring Guide (ESP32 DevKit V1, 30-pin)

## Power
```
12V Li-ion pack ──► DC jack ──► perfboard 7805 (IN)
                               7805 OUT = 5V rail ──► ESP32 VIN, servo red, LCD VDD + LED A
GND of pack, 7805, ESP32, servo, LCD, RC522, IR sensors ── all joined (common ground)
ESP32 3V3 pin ──► RC522 3.3V, IR1 VCC, IR2 VCC
```
* Add a 100 µF capacitor across the 5V rail near the servo (stops brown-outs/resets when it moves).
* The 7805 gets warm from 12 V; keep the load small, and do not run USB and VIN-from-12V at the same time without checking polarity.
* **RC522 must be on 3.3 V – never 5 V.**
* IR modules are powered from 3.3 V so their OUT pin is safe for the ESP32 inputs.

## Pin table
| Part | Part pin | ESP32 pin |
|---|---|---|
| RC522 | SDA (SS) | GPIO 5 |
| RC522 | SCK | GPIO 18 |
| RC522 | MOSI | GPIO 23 |
| RC522 | MISO | GPIO 19 |
| RC522 | RST | GPIO 4 |
| RC522 | 3.3V / GND | 3V3 / GND |
| RC522 | IRQ | not connected |
| IR 1 (before switch) | OUT | GPIO 34 |
| IR 2 (after merge) | OUT | GPIO 35 |
| IR 1 / IR 2 | VCC / GND | 3V3 / GND |
| SG90 servo | signal (yellow/orange) | GPIO 13 |
| SG90 servo | red / brown | 5V rail / GND |
| LCD (I2C backpack) | SDA | GPIO 21 |
| LCD (I2C backpack) | SCL | GPIO 22 |
| LCD (I2C backpack) | VCC / GND | 5V rail / GND |

The backpack is addressed at `0x27` by default (`LCD_I2C_ADDR` in `config.h`); some boards use `0x3F`. If the screen lights up but shows only blocks or nothing, turn the small blue contrast pot on the backpack and check the address with an I2C scanner sketch. The backpack's pull-ups go to 5V; this normally works fine with the ESP32's 3.3V I2C pins. If you want to be strict, add a bidirectional level shifter on SDA/SCL.

## Track layout (what the sensors mean)
```
RFID ─► IR1 ─► [SWITCH servo] ─┬─ MAIN line ─┬─► IR2 ─► exit
                               └─ LOOP line ─┘
```
* **RFID** tap = identifies the train (each train model carries one tag).
* **IR 1** = train entered the junction block. **IR 2** = train left, block clear.
* **Servo** = track switch: `SERVO_MAIN_DEG` (30°) / `SERVO_LOOP_DEG` (110°) in `config.h`. Tune these so the point blades line up with your track.

## Routing rule (AUTO mode, in `web/app.py` → `decide_route`)
| Train type | Route |
|---|---|
| EXPRESS | MAIN always |
| PASSENGER | MAIN, or LOOP if the block is occupied |
| GOODS / FREIGHT | LOOP |

On the website the loop is **Track 3** and the main line is **Track 1**; the servo is **Switch 1A**. The AI dispatcher also moves it when it diverts a lower-priority simulated train from Track 1 to Track 3.

The dashboard can override this: pressing Set MAIN / Set LOOP switches to MANUAL; the toggle button returns to AUTO. Unknown RFID tags are auto-registered as PASSENGER and can be renamed in the Train Registry.

## Offline fallback
If the server is unreachable, the ESP32 still reads tags, alternates the servo between MAIN/LOOP on each scan and shows the UID on the LCD.
