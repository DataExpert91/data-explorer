# Superstore Dashboard: Data Explorer (main page).
#
# Loads the data (the clean demo file or a user upload) and stores it in
# session_state so the other pages can use it.
# The table can be filtered in the sidebar (filters live in components/filters.py).

import pandas as pd
import streamlit as st

from components.filters import sidebar_filters
from components.data_quality import bump_data_version

DEMO_PATH = "data/clean/superstore_clean.csv"

st.title("Data Explorer")

uploaded_file = st.file_uploader("Upload a CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file is not None:
    # File ID distinguishes new uploads that reuse a name and size.
    upload_id = getattr(uploaded_file, "file_id", "")
    file_key = f"{uploaded_file.name}-{uploaded_file.size}-{upload_id}"

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
        st.session_state.pop("chart_settings", None)
        # A new dataset invalidates Data Quality results and its undo snapshot.
        bump_data_version(st.session_state, st.session_state["df"])
        st.session_state.pop("dq_undo", None)
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
    bump_data_version(st.session_state, st.session_state["df"])

# the table we work with: the edited version if it exists, otherwise the original
current_df = st.session_state.get("edited_df", st.session_state["df"])

st.caption(f"Current data: {st.session_state['source']}")
if "edited_df" in st.session_state:
    st.caption("Showing the table with your edits from the Editor page.")

# filters are drawn in the sidebar; the function returns the filtered table
filtered_df = sidebar_filters(current_df)

st.caption(f"Showing {len(filtered_df)} of {len(current_df)} rows")
st.dataframe(filtered_df)
