"""Generate a synthetic Southern Railway (Tamil Nadu) train-movement dataset.

Output: data/railway_dataset.csv   (run:  python data/generate_dataset.py)
It follows the attribute list of the SmartRail AI report: train number/name,
station, arrival/departure, speed, delay, platform, section, status.
"""
import csv
import os
import random
from datetime import datetime, timedelta

random.seed(42)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "railway_dataset.csv")

TRAINS = [("12635", "Vaigai Express", "EXPRESS"), ("12693", "Pearl City Express", "EXPRESS"),
          ("16231", "Mysuru Express", "EXPRESS"), ("56841", "Karur Passenger", "PASSENGER"),
          ("56710", "Salem Passenger", "PASSENGER"), ("06845", "Trichy MEMU", "PASSENGER"),
          ("90112", "Salem Goods", "FREIGHT"), ("90245", "Coimbatore Goods", "FREIGHT")]
SECTIONS = {"Karur-Salem": ["Karur", "Namakkal", "Salem"],
            "Trichy-Karur": ["Trichy", "Musiri", "Karur"],
            "Salem-Erode": ["Salem", "Sankari", "Erode"],
            "Erode-Coimbatore": ["Erode", "Tiruppur", "Coimbatore"]}
BASE_DELAY = {"EXPRESS": 4, "PASSENGER": 9, "FREIGHT": 18}
SPEED = {"EXPRESS": (70, 110), "PASSENGER": (45, 75), "FREIGHT": (30, 55)}

rows = []
start = datetime(2026, 9, 1, 0, 0)
for day in range(60):
    for number, name, ttype in TRAINS:
        for section, stations in SECTIONS.items():
            if random.random() < 0.55:
                continue
            hour = random.choice([4, 6, 8, 10, 13, 16, 18, 21])
            t = start + timedelta(days=day, hours=hour, minutes=random.randint(0, 59))
            rush = 1.6 if hour in (8, 18) else 1.0
            for station in stations:
                delay = max(0, int(random.gauss(BASE_DELAY[ttype] * rush, 6)))
                if random.random() < 0.04:
                    delay += random.randint(30, 90)  # disruption outliers
                dwell = random.randint(2, 6)
                lo, hi = SPEED[ttype]
                status = "On Time" if delay <= 5 else ("Delayed" if delay <= 45 else "Heavily Delayed")
                rows.append([number, name, ttype, section, station, t.isoformat(sep=" "),
                             (t + timedelta(minutes=delay)).isoformat(sep=" "),
                             (t + timedelta(minutes=delay + dwell)).isoformat(sep=" "),
                             random.randint(lo, hi), delay, random.randint(1, 5), status])
                t += timedelta(minutes=random.randint(35, 80))

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["train_number", "train_name", "train_type", "section", "station",
                "scheduled_arrival", "actual_arrival", "departure", "speed_kmph",
                "delay_min", "platform", "status"])
    w.writerows(rows)
print(f"wrote {len(rows)} rows -> {OUT}")
