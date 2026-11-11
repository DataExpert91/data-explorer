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
from components.i18n import render_language_selector, t
from components.session_data import get_active_dataframe
from components.workflow import mark_workflow_stage_complete, render_workflow

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

st.title(t("charts.title"))
render_language_selector()

if "df" not in st.session_state:
    st.warning(t("charts.no_data"))
    st.stop()

# the same table and the same filters as on the Data Explorer page
current_df = get_active_dataframe(st.session_state)
render_workflow("explore")
filtered_df = sidebar_filters(current_df)
if not current_df.columns.is_unique:
    st.stop()

if filtered_df.empty:
    st.info(t("charts.no_rows"))
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
    return (
        t("charts.choice.count_rows")
        if is_chart_choice(column, COUNT_ROWS)
        else format_column(column)
    )


def format_optional_column(column):
    return (
        t("charts.choice.none")
        if is_chart_choice(column, NO_COLOR)
        else format_column(column)
    )


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
            fields = ", ".join(
                t(f"charts.role.{role}") for role in missing_roles
            )
            st.info(t("charts.no_observations_missing", fields=fields))
        else:
            st.info(t("charts.no_observations"))
        st.stop()

    st.caption(
        t(
            "charts.row_count",
            filtered=len(filtered_df),
            total=len(current_df),
            used=used_rows,
        )
    )
    if missing_rows:
        fields = ", ".join(t(f"charts.role.{role}") for role in missing_roles)
        st.caption(t("charts.rows_missing", count=missing_rows, fields=fields))
    if top_n_rows:
        st.caption(t("charts.topn_omits", count=top_n_rows))


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

chart_type = choose(
    t("charts.label.chart_type"),
    ["Bar", "Line", "Scatter", "Histogram", "Box Plot", "Correlation Heatmap"],
    "w_chart_type", "Bar",
    format_func=lambda value: t(f"charts.type.{value}"),
)
prefix = {
    "Box Plot": "w_Box_Plot",
    "Correlation Heatmap": "w_Correlation_Heatmap",
}.get(chart_type, f"w_{chart_type}")


def color_choices(exclude):
    """Columns with few distinct values: good for colouring (and not too many lines)."""
    few = [c for c in all_cols if c not in exclude and filtered_df[c].nunique() <= 20]
    return [NO_COLOR] + few


def categorical_choices(exclude):
    """Low-cardinality non-numeric columns suitable for Box Plot grouping."""
    few = [
        column
        for column in all_cols
        if column not in exclude
        and (
            ptypes.is_bool_dtype(filtered_df[column])
            or not ptypes.is_numeric_dtype(filtered_df[column])
        )
        and filtered_df[column].nunique() <= 20
    ]
    return [NO_COLOR] + few


if chart_type in ("Bar", "Line"):
    # ----- aggregated charts: group by X, then sum / average / median of Y -----
    x_default = first_in(["Order Date" if chart_type == "Line" else "Category"], all_cols)
    x = choose(
        t("charts.label.x_axis"),
        all_cols,
        f"{prefix}_x",
        x_default,
        format_func=format_column,
    )

    y_options = [COUNT_ROWS] + [c for c in num_cols if c != x]
    y = choose(
        t("charts.label.y_axis"),
        y_options,
        f"{prefix}_y",
        first_in(["Sales"], y_options),
        format_func=format_y_choice,
    )

    func_name = None
    if not is_chart_choice(y, COUNT_ROWS):
        func_name = choose(
            t("charts.label.aggregation"),
            list(AGG_FUNCS),
            f"{prefix}_agg",
            "Sum",
            format_func=lambda value: t(f"charts.aggregation.{value}"),
        )

    is_date = ptypes.is_datetime64_any_dtype(filtered_df[x])
    data = plotting_copy(filtered_df)
    x_key = plot_column_by_label[x]
    if is_date:
        freq = choose(
            t("charts.label.date_group"),
            list(DATE_FREQ),
            f"{prefix}_freq",
            "Month",
            format_func=lambda value: t(f"charts.date.{value}"),
        )
        data[x_key] = data[x_key].dt.to_period(DATE_FREQ[freq]).dt.to_timestamp()

    color = choose(
        t("charts.label.color"),
        color_choices([x, y]),
        f"{prefix}_color",
        NO_COLOR,
        format_func=format_optional_column,
    )
    bar_mode = None
    if chart_type == "Bar":
        bar_mode = choose(
            t("charts.label.bar_mode"),
            ["Grouped", "Stacked"],
            f"{prefix}_mode",
            "Grouped",
            format_func=lambda value: t(f"charts.mode.{value}"),
        )
        if bar_mode == "Stacked" and func_name in {"Average", "Median"}:
            st.info(t("charts.stacked_average_note"))
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
        y_label = t("charts.choice.count_rows")
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
        y_label = (
            f"{t(f'charts.aggregation.{func_name}')} "
            f"{t('charts.aggregation.of')} {format_column(y)}"
        )
        valid_value_rows = valid_rows

    top_n_row_count = valid_row_count
    if chart_type == "Bar":
        order = {}
        if not is_date:
            # too many bars are unreadable: keep the top N values of X
            agg[x_key] = agg[x_key].astype(str)
            top_n = choose(
                t("charts.label.top_n"),
                [5, 10, 15, 20, 30, 50],
                f"{prefix}_topn",
                15,
            )
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
            barmode={"Grouped": "group", "Stacked": "stack"}[bar_mode],
            category_orders=order,
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
    if chart_type == "Correlation Heatmap":
        st.info(t("charts.heatmap_needs_two"))
    else:
        st.info(t("charts.needs_numeric"))
    st.stop()

elif chart_type == "Scatter":
    # ----- scatter: every row is a point -----
    x = choose(
        t("charts.label.x_number"), num_cols, f"{prefix}_x", first_in(["Sales"], num_cols),
        format_func=format_column,
    )
    y = choose(
        t("charts.label.y_number"), num_cols, f"{prefix}_y", first_in(["Profit"], num_cols),
        format_func=format_column,
    )
    color = choose(
        t("charts.label.color"), color_choices([x, y]), f"{prefix}_color", NO_COLOR,
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

elif chart_type == "Histogram":
    # ----- histogram: how the values of one column are distributed -----
    x = choose(
        t("charts.label.column_number"), num_cols, f"{prefix}_x", first_in(["Sales"], num_cols),
        format_func=format_column,
    )
    color = choose(
        t("charts.label.color"), color_choices([x]), f"{prefix}_color", NO_COLOR,
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

elif chart_type == "Correlation Heatmap":
    if len(num_cols) < 2:
        st.info(t("charts.heatmap_needs_two"))
        st.stop()

    selected_key = f"{prefix}_columns"
    default_columns = num_cols[:20]
    if selected_key not in st.session_state:
        if selected_key in saved:
            selected_columns = [
                column for column in saved[selected_key] if column in num_cols
            ][:20]
        else:
            selected_columns = default_columns
        st.session_state[selected_key] = selected_columns
    else:
        current_selection = st.session_state[selected_key]
        valid_selection = [
            column for column in current_selection if column in num_cols
        ][:20]
        if valid_selection != current_selection:
            st.session_state[selected_key] = valid_selection

    selected_columns = st.multiselect(
        t("charts.label.numeric_columns"),
        num_cols,
        key=selected_key,
        format_func=format_column,
        max_selections=20,
    )
    saved[selected_key] = selected_columns
    if len(selected_columns) < 2:
        st.info(t("charts.select_two"))
        st.stop()

    chart_df = plotting_copy(filtered_df)
    selected_keys = [plot_column_by_label[column] for column in selected_columns]
    correlation = chart_df[selected_keys].corr(method="pearson")
    display_labels = [format_column(column) for column in selected_columns]
    correlation.index = display_labels
    correlation.columns = display_labels
    st.caption(t("charts.pairwise"))
    fig = px.imshow(
        correlation,
        color_continuous_scale="RdBu",
        color_continuous_midpoint=0,
        zmin=-1,
        zmax=1,
        text_auto=".2f",
        aspect="auto",
        labels={
            "x": t("charts.axis.column"),
            "y": t("charts.axis.column"),
            "color": t("charts.axis.correlation"),
        },
        template=TEMPLATE,
    )

else:
    # ----- box plot: distribution of a numeric column, optionally grouped -----
    y = choose(
        t("charts.label.numeric_column"),
        num_cols,
        f"{prefix}_y",
        first_in(["Sales"], num_cols),
        format_func=format_column,
    )
    group_by = choose(
        t("charts.label.group_by"),
        categorical_choices([y]),
        f"{prefix}_group",
        NO_COLOR,
        format_func=format_optional_column,
    )
    color = choose(
        t("charts.label.color"),
        color_choices([y, group_by]),
        f"{prefix}_color",
        NO_COLOR,
        format_func=format_optional_column,
    )

    chart_df = plotting_copy(filtered_df)
    y_key = plot_column_by_label[y]
    group_key = (
        None if is_chart_choice(group_by, NO_COLOR) else plot_column_by_label[group_by]
    )
    color_key = None if is_chart_choice(color, NO_COLOR) else plot_column_by_label[color]
    labels = {y_key: format_column(y)}
    required_fields = [("Y", y_key)]
    if group_key is not None:
        labels[group_key] = format_column(group_by)
        required_fields.append(("Group By", group_key))
    if color_key is not None:
        labels[color_key] = format_column(color)
        required_fields.append(("Color", color_key))

    valid_rows, missing_roles = chart_row_mask(chart_df, required_fields)
    show_chart_row_feedback(
        int(valid_rows.sum()), len(filtered_df) - int(valid_rows.sum()), missing_roles
    )
    chart_data = chart_df.loc[valid_rows]
    fig = px.box(
        chart_data,
        x=group_key,
        y=y_key,
        color=color_key,
        points="outliers",
        labels=labels,
        template=TEMPLATE,
    )

st.plotly_chart(fig)
mark_workflow_stage_complete(st.session_state, "explore")
