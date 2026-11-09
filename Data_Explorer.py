# Superstore Dashboard: Data Explorer (main page).
#
# Loads the data (the clean demo file or a user upload) and stores it in
# session_state so the other pages can use it.
# Filters in the sidebar adapt to the columns of whatever file is loaded.

import pandas as pd
import streamlit as st
from pandas.api import types as ptypes

DEMO_PATH = "data/clean/superstore_clean.csv"

st.title("Data Explorer")

uploaded_file = st.file_uploader("Upload a CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file is not None:
    # an id of the uploaded file: name + size
    file_key = f"{uploaded_file.name}-{uploaded_file.size}"

    # react only to a NEW file; reruns with the same file are skipped
    if st.session_state.get("file_key") != file_key:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        st.session_state["df"] = df
        st.session_state["source"] = uploaded_file.name
        st.session_state["file_key"] = file_key

        # a new file means the old edits and filter choices no longer apply
        st.session_state.pop("edited_df", None)
        st.session_state.pop("editor", None)
        st.session_state.pop("filters", None)
        st.session_state.pop("filter_cols", None)
        for key in list(st.session_state.keys()):
            if key.startswith("w_"):  # all filter widgets
                del st.session_state[key]

elif "df" not in st.session_state:
    # first visit and no upload: load the demo file once
    st.session_state["df"] = pd.read_csv(
        DEMO_PATH,
        parse_dates=["Order Date", "Ship Date"],
        dtype={"Postal Code": str},
    )
    st.session_state["source"] = "demo data (superstore_clean.csv)"

# the table we work with: the edited version if it exists, otherwise the original
current_df = st.session_state.get("edited_df", st.session_state["df"])

st.caption(f"Current data: {st.session_state['source']}")
if "edited_df" in st.session_state:
    st.caption("Showing the table with your edits from the Editor page.")

# ---------- Sidebar filters ----------
st.sidebar.header("Filters")

# saved filter values: {column name: value}. Widgets forget their value when
# the user leaves the page, so we keep a copy here and restore it on return.
saved = st.session_state.setdefault("filters", {})

# 1. which columns to filter by
columns = list(current_df.columns)

if "w_filter_cols" not in st.session_state:
    wanted = st.session_state.get("filter_cols", ["Category"])
    st.session_state["w_filter_cols"] = [c for c in wanted if c in columns]

chosen = st.sidebar.multiselect(
    "Filter by columns",
    options=columns,
    key="w_filter_cols",
)
st.session_state["filter_cols"] = chosen

# 2. one filter per chosen column, the widget depends on the column type
filtered_df = current_df

for col in chosen:
    series = current_df[col].dropna()
    if series.empty:
        continue
    key = f"w_{col}"

    if ptypes.is_datetime64_any_dtype(series):
        # dates: a range picker
        low, high = series.min().date(), series.max().date()
        if key not in st.session_state:
            start, end = saved.get(col, (low, high))
            start, end = max(start, low), min(end, high)
            if start > end:
                start, end = low, high
            st.session_state[key] = (start, end)

        picked = st.sidebar.date_input(col, min_value=low, max_value=high, key=key)

        # while the user is choosing, the picker returns only one date
        if len(picked) == 2:
            saved[col] = picked
            filtered_df = filtered_df[
                (filtered_df[col] >= pd.Timestamp(picked[0]))
                & (filtered_df[col] < pd.Timestamp(picked[1]) + pd.Timedelta(days=1))
            ]

    elif ptypes.is_numeric_dtype(series) and not ptypes.is_bool_dtype(series):
        # numbers: a range slider
        cast = int if ptypes.is_integer_dtype(series) else float
        low, high = cast(series.min()), cast(series.max())
        if low == high:
            continue  # a single value, nothing to filter
        if key not in st.session_state:
            start, end = saved.get(col, (low, high))
            start, end = cast(max(start, low)), cast(min(end, high))
            if start > end:
                start, end = low, high
            st.session_state[key] = (start, end)

        start, end = st.sidebar.slider(col, min_value=low, max_value=high, key=key)
        saved[col] = (start, end)
        filtered_df = filtered_df[filtered_df[col].between(start, end)]

    else:
        # text (and everything else): pick values from a list
        options = sorted(series.astype(str).unique())
        if key not in st.session_state:
            old = saved.get(col, options)
            st.session_state[key] = [v for v in old if v in options]

        selected = st.sidebar.multiselect(col, options=options, key=key)
        saved[col] = selected
        filtered_df = filtered_df[filtered_df[col].astype(str).isin(selected)]

st.caption(f"Showing {len(filtered_df)} of {len(current_df)} rows")
st.dataframe(filtered_df)