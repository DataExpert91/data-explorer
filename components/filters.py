# Sidebar filters that adapt to the columns of the current table.
# Used by the Data Explorer and Charts pages, so both show the same filters.

import pandas as pd
import streamlit as st
from pandas.api import types as ptypes


def sidebar_filters(current_df):
    """Draw the filter widgets in the sidebar and return the filtered table."""
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

    return filtered_df