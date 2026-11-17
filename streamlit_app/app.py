"""SmartRail AI - Streamlit analytics (EDA, delays, throughput + live prototype data).

Run:  streamlit run streamlit_app/app.py
"""
import os
import sqlite3

import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "data", "railway_dataset.csv")
DB = os.environ.get("DB_PATH", os.path.join(ROOT, "web", "smartrail.db"))

st.set_page_config(page_title="SmartRail AI Analytics", page_icon="🚆", layout="wide")
st.title("🚆 SmartRail AI – Railway Analytics")
st.caption("Southern Railway • Tamil Nadu Operations — exploratory analysis & section throughput")


@st.cache_data
def load_csv(path):
    df = pd.read_csv(path, parse_dates=["scheduled_arrival", "actual_arrival", "departure"])
    df = df.drop_duplicates().dropna(subset=["train_number", "station"])
    df["hour"] = df["scheduled_arrival"].dt.hour
    df["date"] = df["scheduled_arrival"].dt.date
    return df


if not os.path.exists(CSV):
    st.error("Dataset missing. Run:  python data/generate_dataset.py")
    st.stop()
df = load_csv(CSV)

# ---- sidebar filters
st.sidebar.header("Filters")
types = st.sidebar.multiselect("Train type", sorted(df.train_type.unique()), default=sorted(df.train_type.unique()))
sections = st.sidebar.multiselect("Section", sorted(df.section.unique()), default=sorted(df.section.unique()))
f = df[df.train_type.isin(types) & df.section.isin(sections)]

tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Delay analysis", "Section throughput", "Live prototype"])

with tab1:
    c = st.columns(4)
    c[0].metric("Records", f"{len(f):,}")
    c[1].metric("Avg delay (min)", f"{f.delay_min.mean():.1f}")
    c[2].metric("On-time %", f"{(f.status == 'On Time').mean() * 100:.1f}%")
    c[3].metric("Avg speed (km/h)", f"{f.speed_kmph.mean():.0f}")
    l, r = st.columns(2)
    l.subheader("Status distribution")
    l.bar_chart(f.status.value_counts())
    r.subheader("Records by train type")
    r.bar_chart(f.train_type.value_counts())
    st.subheader("Descriptive statistics")
    st.dataframe(f[["speed_kmph", "delay_min", "platform"]].describe())
    st.subheader("Data sample")
    st.dataframe(f.head(100))

with tab2:
    l, r = st.columns(2)
    l.subheader("Average delay by train type")
    l.bar_chart(f.groupby("train_type").delay_min.mean())
    r.subheader("Average delay by hour of day")
    r.line_chart(f.groupby("hour").delay_min.mean())
    st.subheader("Top 10 most delayed trains")
    st.dataframe(f.groupby(["train_number", "train_name"]).delay_min.mean()
                 .sort_values(ascending=False).head(10).round(1).reset_index())
    st.subheader("Delay histogram")
    st.bar_chart(pd.cut(f.delay_min, bins=[-1, 5, 15, 30, 60, 200]).value_counts().sort_index()
                 .rename(index=str))

with tab3:
    st.subheader("Trains per section")
    st.bar_chart(f.groupby("section").train_number.count())
    st.subheader("Daily throughput (movements per day)")
    st.line_chart(f.groupby("date").size())
    st.subheader("Section utilisation by hour (heatmap table)")
    st.dataframe(f.pivot_table(index="section", columns="hour", values="train_number",
                               aggfunc="count", fill_value=0))

with tab4:
    st.subheader("Movements recorded by the ESP32 prototype")
    if os.path.exists(DB):
        con = sqlite3.connect(DB)
        mv = pd.read_sql("SELECT * FROM movements", con)
        con.close()
        if mv.empty:
            st.info("No movements yet. Scan an RFID tag and trigger IR 1 then IR 2.")
        else:
            mv["exit_time"] = pd.to_datetime(mv.exit_ts, unit="s")
            a, b = st.columns(2)
            a.metric("Trains processed", len(mv))
            b.metric("Avg transit (s)", f"{mv.transit_s.mean():.1f}")
            st.bar_chart(mv.route.value_counts())
            st.dataframe(mv.sort_values("id", ascending=False))
    else:
        st.info("Start the Flask server first (web/app.py) so the database exists.")
