# Charts page.
#
# Builds an interactive Plotly chart from the filtered table.
# The user picks the chart type and the columns. The filters in the sidebar
# are the same as on the Data Explorer page (components/filters.py).

from collections import Counter
from enum import Enum

import plotly.express as px
import streamlit as st
from pandas.api import types as ptypes

from components.filters import sidebar_filters
from components.session_data import get_active_dataframe

class _ChartChoice(Enum):
    COUNT_ROWS = "count_rows"
    NO_COLOR = "no_color"


COUNT_ROWS = _ChartChoice.COUNT_ROWS
NO_COLOR = _ChartChoice.NO_COLOR
COUNT_ROWS_LABEL = "Count of rows"
NO_COLOR_LABEL = "(none)"
COUNT_ROWS_COLUMN = "__chart_count_rows"
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

if filtered_df.empty:
    st.info("No rows match the current filters.")
    st.stop()

# saved chart settings: widgets forget their value when the page is left
saved = st.session_state.setdefault("chart_settings", {})


def choose(label, options, key, default, format_func=None):
    """A selectbox that restores the previous choice when the user comes back."""
    if key not in st.session_state:
        old = saved.get(key, default)
        if is_chart_choice(old, COUNT_ROWS):
            old = COUNT_ROWS
        elif is_chart_choice(old, NO_COLOR):
            old = NO_COLOR
        st.session_state[key] = old if old in options else default
    selectbox_options = {"format_func": format_func} if format_func is not None else {}
    value = st.selectbox(label, options, key=key, **selectbox_options)
    saved[key] = value
    return value


def first_in(candidates, options):
    """The first candidate that exists in options, otherwise the first option."""
    for name in candidates:
        if name in options:
            return name
    return options[0]


all_cols = list(filtered_df.columns)
display_label_counts = Counter(str(column) for column in all_cols)


def format_column(column):
    """Keep normal string labels readable and disambiguate other labels."""
    label = str(column)
    if (
        not isinstance(column, str)
        or display_label_counts[label] > 1
        or label in {COUNT_ROWS_LABEL, NO_COLOR_LABEL}
    ):
        position = filtered_df.columns.get_loc(column)
        return f"{label} ({type(column).__name__}, column {position + 1})"
    return label


def format_y_choice(column):
    return COUNT_ROWS_LABEL if is_chart_choice(column, COUNT_ROWS) else format_column(column)


def format_optional_column(column):
    return NO_COLOR_LABEL if is_chart_choice(column, NO_COLOR) else format_column(column)


def is_chart_choice(value, choice):
    """Recognize sentinel values retained across Streamlit script reruns."""
    return (
        isinstance(value, Enum)
        and type(value).__name__ == type(choice).__name__
        and value.name == choice.name
    )


def chart_row_mask(source_df, required_fields):
    """Return rows with values in every field required by this chart."""
    keys = [key for _, key in required_fields]
    mask = source_df[keys].notna().all(axis=1)
    missing_roles = [
        role for role, key in required_fields if source_df[key].isna().any()
    ]
    return mask, missing_roles


def show_chart_row_feedback(used_rows, missing_rows, missing_roles, top_n_rows=0):
    if used_rows == 0:
        if missing_roles:
            fields = ", ".join(missing_roles)
            st.info(
                "No observations remain after excluding rows with missing "
                f"chart fields ({fields})."
            )
        else:
            st.info("No observations remain for this chart.")
        st.stop()

    st.caption(
        f"Charts use {len(filtered_df)} of {len(current_df)} rows after shared filters; "
        f"the chart represents {used_rows} of {len(filtered_df)} filtered rows."
    )
    if missing_rows:
        fields = ", ".join(missing_roles)
        st.caption(
            f"{missing_rows} rows excluded because selected chart fields are "
            f"missing ({fields})."
        )
    if top_n_rows:
        st.caption(f"Top N omits {top_n_rows} otherwise eligible rows.")


# Plotly Express can treat an integer column label as a positional selector.
# Give only the plotting dataframe unique temporary labels, while chart choices
# and the session dataframe keep the original typed labels.
plot_column_names = [f"__chart_column_{position}" for position in range(len(all_cols))]
plot_column_by_label = dict(zip(all_cols, plot_column_names))


def plotting_copy(source_df):
    chart_df = source_df.copy(deep=False)
    chart_df.columns = plot_column_names
    return chart_df


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
    x = choose(
        "X axis", all_cols, f"{prefix}_x", x_default, format_func=format_column
    )

    y_options = [COUNT_ROWS] + [c for c in num_cols if c != x]
    y = choose(
        "Y axis",
        y_options,
        f"{prefix}_y",
        first_in(["Sales"], y_options),
        format_func=format_y_choice,
    )

    func_name = None
    if not is_chart_choice(y, COUNT_ROWS):
        func_name = choose("Aggregation", list(AGG_FUNCS), f"{prefix}_agg", "Sum")

    is_date = ptypes.is_datetime64_any_dtype(filtered_df[x])
    data = plotting_copy(filtered_df)
    x_key = plot_column_by_label[x]
    if is_date:
        freq = choose("Group dates by", list(DATE_FREQ), f"{prefix}_freq", "Month")
        data[x_key] = data[x_key].dt.to_period(DATE_FREQ[freq]).dt.to_timestamp()

    color = choose(
        "Color by (optional)",
        color_choices([x, y]),
        f"{prefix}_color",
        NO_COLOR,
        format_func=format_optional_column,
    )
    color_arg = None if is_chart_choice(color, NO_COLOR) else color
    x_key = plot_column_by_label[x]
    y_key = COUNT_ROWS_COLUMN if is_chart_choice(y, COUNT_ROWS) else plot_column_by_label[y]
    color_key = None if color_arg is None else plot_column_by_label[color_arg]
    group_cols = [x_key] if color_key is None else [x_key, color_key]

    required_fields = [("X", x_key)]
    if not is_chart_choice(y, COUNT_ROWS):
        required_fields.append(("Y", y_key))
    if color_key is not None:
        required_fields.append(("Color", color_key))
    valid_rows, missing_roles = chart_row_mask(data, required_fields)
    valid_row_count = int(valid_rows.sum())

    if valid_row_count == 0:
        show_chart_row_feedback(0, len(filtered_df), missing_roles)

    if is_chart_choice(y, COUNT_ROWS):
        agg = data.groupby(group_cols).size().reset_index(name=y_key)
        y_label = COUNT_ROWS_LABEL
        valid_value_rows = valid_rows
    else:
        if func_name == "Sum":
            agg = (
                data.groupby(group_cols)[y_key]
                .sum(min_count=1)
                .reset_index()
            )
        else:
            agg = data.groupby(group_cols)[y_key].agg(AGG_FUNCS[func_name]).reset_index()
        y_label = f"{func_name} of {format_column(y)}"
        valid_value_rows = valid_rows

    top_n_row_count = valid_row_count
    if chart_type == "Bar":
        order = {}
        if not is_date:
            # too many bars are unreadable: keep the top N values of X
            agg[x_key] = agg[x_key].astype(str)
            top_n = choose("Show top N values", [5, 10, 15, 20, 30, 50], f"{prefix}_topn", 15)
            totals = agg.groupby(x_key)[y_key].sum().nlargest(top_n)
            agg = agg[agg[x_key].isin(totals.index)]
            order = {x_key: list(totals.index)}  # biggest bar first
            top_n_mask = valid_value_rows & data[x_key].astype(str).isin(totals.index)
            top_n_row_count = int(top_n_mask.sum())
        else:
            agg = agg.sort_values(x_key)
        labels = {x_key: format_column(x), y_key: y_label}
        if color_key is not None:
            labels[color_key] = format_column(color_arg)
        fig = px.bar(
            agg, x=x_key, y=y_key, color=color_key,
            barmode="group", category_orders=order,
            labels=labels, template=TEMPLATE,
        )
    else:
        agg = agg.sort_values(x_key)
        labels = {x_key: format_column(x), y_key: y_label}
        if color_key is not None:
            labels[color_key] = format_column(color_arg)
        fig = px.line(
            agg, x=x_key, y=y_key, color=color_key,
            markers=True, labels=labels, template=TEMPLATE,
        )

    show_chart_row_feedback(
        top_n_row_count,
        len(filtered_df) - valid_row_count,
        missing_roles,
        valid_row_count - top_n_row_count,
    )

elif not num_cols:
    st.info("This chart needs a numeric column, and the table has none.")
    st.stop()

elif chart_type == "Scatter":
    # ----- scatter: every row is a point -----
    x = choose(
        "X axis (number)", num_cols, f"{prefix}_x", first_in(["Sales"], num_cols),
        format_func=format_column,
    )
    y = choose(
        "Y axis (number)", num_cols, f"{prefix}_y", first_in(["Profit"], num_cols),
        format_func=format_column,
    )
    color = choose(
        "Color by (optional)", color_choices([x, y]), f"{prefix}_color", NO_COLOR,
        format_func=format_optional_column,
    )
    chart_df = plotting_copy(filtered_df)
    labels = {
        plot_column_by_label[x]: format_column(x),
        plot_column_by_label[y]: format_column(y),
    }
    color_key = None if is_chart_choice(color, NO_COLOR) else plot_column_by_label[color]
    if color_key is not None:
        labels[color_key] = format_column(color)
    required_fields = [("X", plot_column_by_label[x]), ("Y", plot_column_by_label[y])]
    if color_key is not None:
        required_fields.append(("Color", color_key))
    valid_rows, missing_roles = chart_row_mask(chart_df, required_fields)
    show_chart_row_feedback(
        int(valid_rows.sum()), len(filtered_df) - int(valid_rows.sum()), missing_roles
    )
    chart_data = chart_df.loc[valid_rows]
    fig = px.scatter(
        chart_data, x=plot_column_by_label[x], y=plot_column_by_label[y], color=color_key,
        opacity=0.6, labels=labels, template=TEMPLATE,
    )

else:
    # ----- histogram: how the values of one column are distributed -----
    x = choose(
        "Column (number)", num_cols, f"{prefix}_x", first_in(["Sales"], num_cols),
        format_func=format_column,
    )
    color = choose(
        "Color by (optional)", color_choices([x]), f"{prefix}_color", NO_COLOR,
        format_func=format_optional_column,
    )
    chart_df = plotting_copy(filtered_df)
    x_key = plot_column_by_label[x]
    color_key = None if is_chart_choice(color, NO_COLOR) else plot_column_by_label[color]
    labels = {x_key: format_column(x)}
    if color_key is not None:
        labels[color_key] = format_column(color)
    required_fields = [("X", x_key)]
    if color_key is not None:
        required_fields.append(("Color", color_key))
    valid_rows, missing_roles = chart_row_mask(chart_df, required_fields)
    show_chart_row_feedback(
        int(valid_rows.sum()), len(filtered_df) - int(valid_rows.sum()), missing_roles
    )
    chart_data = chart_df.loc[valid_rows]
    fig = px.histogram(
        chart_data, x=x_key, color=color_key,
        barmode="overlay", opacity=0.75, labels=labels, template=TEMPLATE,
    )

st.plotly_chart(fig)
