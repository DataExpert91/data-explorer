# Superstore Dashboard: main page.

# Loads the data (the clean demo file or a user upload) and stores it in
# session_state so the other pages can use it.

import pandas as pd
import streamlit as st

DEMO_PATH = "data/clean/superstore_clean.csv"

st.title("Dashboard")

uploaded_file = st.file_uploader("Upload a CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file is not None:
    # user's own file: pick the reader by file extension
    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
else:
    # no upload: fall back to the clean demo file
    df = pd.read_csv(
        DEMO_PATH,
        parse_dates=["Order Date", "Ship Date"],
        dtype={"Postal Code": str},
    )


st.session_state["df"] = df 
st.dataframe(df)
