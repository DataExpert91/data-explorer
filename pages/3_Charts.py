# Charts page.
#
# Builds an interactive Plotly chart from the filtered table.
# The user picks the chart type and the columns. The filters in the sidebar
# are the same as on the Data Explorer page (components/filters.py).

import plotly.express as px
import streamlit as st
from pandas.api import types as ptypes

from components.filters import sidebar_filters
from components.session_data import get_active_dataframe

COUNT_ROWS = "Count of rows"
NO_COLOR = "(none)"
DATE_FREQ = {"Day": "D", "Week": "W", "Month": "M", "Quarter": "Q", "Year": "Y"}
AGG_FUNCS = {"Sum": "sum", "Average": "mean", "Median": "median"}
TEMPLATE = "plotly_white"

st.title("Charts")

if "df" not in st.session_state:
    st.warning("No data loaded. Please open the main page first.")
    st.stop()

# the same table and the same filters as on the Data Explorer page
current_df = get_active_dataframe(st.session_state)
filtered_df = sidebar_filters(current_df)
if not current_df.columns.is_unique:
    st.stop()

st.caption(
    f"Charts use {len(filtered_df)} of {len(current_df)} rows. "
    "Change the filters in the sidebar."
)

if filtered_df.empty:
    st.info("No rows match the current filters.")
    st.stop()

# saved chart settings: widgets forget their value when the page is left
saved = st.session_state.setdefault("chart_settings", {})


def choose(label, options, key, default):
    """A selectbox that restores the previous choice when the user comes back."""
    if key not in st.session_state:
        old = saved.get(key, default)
        st.session_state[key] = old if old in options else default
    value = st.selectbox(label, options, key=key)
    saved[key] = value
    return value


def first_in(candidates, options):
    """The first candidate that exists in options, otherwise the first option."""
    for name in candidates:
        if name in options:
            return name
    return options[0]


all_cols = list(filtered_df.columns)
num_cols = [
    c for c in all_cols
    if ptypes.is_numeric_dtype(filtered_df[c]) and not ptypes.is_bool_dtype(filtered_df[c])
]

chart_type = choose("Chart type", ["Bar", "Line", "Scatter", "Histogram"], "w_chart_type", "Bar")
prefix = f"w_{chart_type}"  # every chart type remembers its own settings


def color_choices(exclude):
    """Columns with few distinct values: good for colouring (and not too many lines)."""
    few = [c for c in all_cols if c not in exclude and filtered_df[c].nunique() <= 20]
    return [NO_COLOR] + few


if chart_type in ("Bar", "Line"):
    # ----- aggregated charts: group by X, then sum / average / median of Y -----
    x_default = first_in(["Order Date" if chart_type == "Line" else "Category"], all_cols)
    x = choose("X axis", all_cols, f"{prefix}_x", x_default)

    y_options = [COUNT_ROWS] + [c for c in num_cols if c != x]
    y = choose("Y axis", y_options, f"{prefix}_y", first_in(["Sales"], y_options))

    func_name = None
    if y != COUNT_ROWS:
        func_name = choose("Aggregation", list(AGG_FUNCS), f"{prefix}_agg", "Sum")

    data = filtered_df
    is_date = ptypes.is_datetime64_any_dtype(data[x])
    if is_date:
        freq = choose("Group dates by", list(DATE_FREQ), f"{prefix}_freq", "Month")
        data = data.copy()
        data[x] = data[x].dt.to_period(DATE_FREQ[freq]).dt.to_timestamp()

    color = choose("Color by (optional)", color_choices([x, y]), f"{prefix}_color", NO_COLOR)
    color_arg = None if color == NO_COLOR else color
    group_cols = [x] if color_arg is None else [x, color_arg]

    if y == COUNT_ROWS:
        agg = data.groupby(group_cols).size().reset_index(name=COUNT_ROWS)
        y_label = COUNT_ROWS
    else:
        agg = data.groupby(group_cols)[y].agg(AGG_FUNCS[func_name]).reset_index()
        y_label = f"{func_name} of {y}"

    if chart_type == "Bar":
        order = {}
        if not is_date:
            # too many bars are unreadable: keep the top N values of X
            agg[x] = agg[x].astype(str)
            top_n = choose("Show top N values", [5, 10, 15, 20, 30, 50], f"{prefix}_topn", 15)
            totals = agg.groupby(x)[y].sum().nlargest(top_n)
            agg = agg[agg[x].isin(totals.index)]
            order = {x: list(totals.index)}  # biggest bar first
        else:
            agg = agg.sort_values(x)
        fig = px.bar(
            agg, x=x, y=y, color=color_arg,
            barmode="group", category_orders=order,
            labels={y: y_label}, template=TEMPLATE,
        )
    else:
        agg = agg.sort_values(x)
        fig = px.line(
            agg, x=x, y=y, color=color_arg,
            markers=True, labels={y: y_label}, template=TEMPLATE,
        )

elif not num_cols:
    st.info("This chart needs a numeric column, and the table has none.")
    st.stop()

elif chart_type == "Scatter":
    # ----- scatter: every row is a point -----
    x = choose("X axis (number)", num_cols, f"{prefix}_x", first_in(["Sales"], num_cols))
    y = choose("Y axis (number)", num_cols, f"{prefix}_y", first_in(["Profit"], num_cols))
    color = choose("Color by (optional)", color_choices([x, y]), f"{prefix}_color", NO_COLOR)
    fig = px.scatter(
        filtered_df, x=x, y=y, color=None if color == NO_COLOR else color,
        opacity=0.6, template=TEMPLATE,
    )

else:
    # ----- histogram: how the values of one column are distributed -----
    x = choose("Column (number)", num_cols, f"{prefix}_x", first_in(["Sales"], num_cols))
    color = choose("Color by (optional)", color_choices([x]), f"{prefix}_color", NO_COLOR)
    fig = px.histogram(
        filtered_df, x=x, color=None if color == NO_COLOR else color,
        barmode="overlay", opacity=0.75, template=TEMPLATE,
    )

st.plotly_chart(fig)
