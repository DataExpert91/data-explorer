# Sidebar filters that adapt to the columns of the current table.
# Used by the Data Explorer and Charts pages, so both show the same filters.

from collections import Counter

import pandas as pd
import streamlit as st
from pandas.api import types as ptypes


def sidebar_filters(current_df):
    """Draw the filter widgets in the sidebar and return the filtered table."""
    if not current_df.columns.is_unique:
        st.warning(
            "Filtering is unavailable because this dataset has duplicate column names. "
            "Rename the duplicate column names to enable filtering."
        )
        return current_df

    st.sidebar.header("Filters")

    # saved filter values: {column name: value}. Widgets forget their value when
    # the user leaves the page, so we keep a copy here and restore it on return.
    saved = st.session_state.setdefault("filters", {})

    # 1. which columns to filter by
    columns = list(current_df.columns)
    display_labels = [str(column) for column in columns]
    display_label_counts = Counter(display_labels)

    def format_column_position(position):
        label = display_labels[position]
        if display_label_counts[label] > 1:
            column_type = type(columns[position]).__name__
            return f"{label} ({column_type}, column {position + 1})"
        return label

    # Filter widget keys are positional, so clear them when the active schema
    # changes. The saved values remain keyed by the original column labels.
    schema = tuple(
        (
            type(column).__module__,
            type(column).__qualname__,
            repr(column),
            repr(dtype),
        )
        for column, dtype in zip(current_df.columns, current_df.dtypes)
    )
    previous_schema = st.session_state.get("_filter_widget_schema")
    if previous_schema != schema:
        for state_key in list(st.session_state):
            if state_key.startswith("w_filter_value_"):
                del st.session_state[state_key]
        if previous_schema is not None:
            previous_dtypes = {
                entry[:3]: entry[3]
                for entry in previous_schema
            }
            for column, dtype in zip(current_df.columns, current_df.dtypes):
                column_identity = (
                    type(column).__module__,
                    type(column).__qualname__,
                    repr(column),
                )
                if (
                    column_identity in previous_dtypes
                    and previous_dtypes[column_identity] != repr(dtype)
                ):
                    saved.pop(column, None)
        wanted = st.session_state.get("filter_cols", ["Category"])
        st.session_state["w_filter_cols"] = [
            position
            for position, column in enumerate(columns)
            if column in wanted
        ]
        st.session_state["_filter_widget_schema"] = schema

    if "w_filter_cols" not in st.session_state:
        wanted = st.session_state.get("filter_cols", ["Category"])
        st.session_state["w_filter_cols"] = [
            position
            for position, column in enumerate(columns)
            if column in wanted
        ]

    chosen_positions = st.sidebar.multiselect(
        "Filter by columns",
        options=list(range(len(columns))),
        key="w_filter_cols",
        format_func=format_column_position,
    )
    chosen = [columns[position] for position in chosen_positions]
    st.session_state["filter_cols"] = chosen

    # 2. one filter per chosen column, the widget depends on the column type
    filtered_df = current_df

    for column_position in chosen_positions:
        col = columns[column_position]
        series = current_df[col].dropna()
        if series.empty:
            continue
        key = f"w_filter_value_{column_position}"

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
