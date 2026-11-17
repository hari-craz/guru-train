# SmartRail AI – Intelligent Train Traffic Control (prototype)

ESP32 + RC522 RFID + 2× IR + SG90 servo + 16×2 LCD ⇄ WebSocket ⇄ Flask control-room site, plus a Streamlit analytics app.

```
web/             Flask + WebSocket server and sidebar control room (Dashboard/CTC track display, Live Monitoring,
                 Train/Station/Track Management, Scheduling, AI Dispatch, Alerts, Analytics)
streamlit_app/   Streamlit EDA / delay / throughput app
data/            generate_dataset.py -> railway_dataset.csv (synthetic, 2.6k rows)
firmware/        ESP32 Arduino sketch (edit config.h first)
docs/WIRING.md   pin table, power, track layout, routing rules
```

## 1. Run the website
```bash
cd web
pip install -r requirements.txt
python app.py            # http://localhost:5000
```
The 5-track corridor is simulated (with AI conflict prediction and diversion); the ESP32 rig is the real **Switch 1A** (Track 1 main / Track 3 loop). A tag scan puts a physical train on the track display.
Seed login: `controller@smartrail.gov.in` / `controller123` (override with env `SEED_EMAIL`, `SEED_PASSWORD`; set `SECRET_KEY` and `DEVICE_TOKEN` in production).
No hardware yet? Use the **Demo Simulator** on the Control Room page (Scan RFID → IR 1 → IR 2).

## 2. Streamlit analytics
```bash
pip install -r streamlit_app/requirements.txt
python data/generate_dataset.py
streamlit run streamlit_app/app.py
```

## 3. Flash the ESP32 and connect
1. Libraries: MFRC522, WebSockets (Markus Sattler), ArduinoJson, ESP32Servo, LiquidCrystal_I2C. Board: **ESP32 Dev Module**.
2. Wire it per `docs/WIRING.md`, upload `firmware/smartrail_esp32` (arduino-cli: `arduino-cli compile --fqbn esp32:esp32:esp32 --upload -p COM20 firmware/smartrail_esp32`).
3. The ESP32 **creates its own Wi-Fi**: `SmartRail-ESP32` / `smartrail123` (change in `config.h`). Join it from the laptop, then run `python web/app.py`.
   The server connects to `ws://192.168.4.1:81` by itself (override with env `ESP_URL`), and the dashboard shows "ESP32 Online".
   The laptop has no internet while joined to that Wi-Fi; the site works offline (Chart.js is bundled).
4. Tap a tag: the Event Log shows its UID. Rename it in Train Management and pick the category.

## Deploy to Railway
Point the service at `web/` (Procfile included, single gunicorn worker because state is in memory). Set `SECRET_KEY`, `DEVICE_TOKEN`, `SEED_PASSWORD`. Set `ESP_URL=""` (a cloud server cannot reach the ESP32's private Wi-Fi), so the rig is local-only unless you add a bridge. Use a volume for `DB_PATH` if you want history to survive redeploys.

## Notes
* The firmware compiles for "ESP32 Dev Module" (arduino-cli, ESP32 core 3.3.11) but has not been flashed to a real board; the server flow was tested with a simulated device.
* Servo angles, IR sensitivity (blue pot on each module) and LCD contrast pot (on the I2C backpack) need tuning on the real rig.
