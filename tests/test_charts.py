from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt
import streamlit as st
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "Data_Explorer.py"
CHARTS_PAGE = "pages/3_Charts.py"


def _open_charts(df, monkeypatch):
    figures = []
    monkeypatch.setattr(
        st,
        "plotly_chart",
        lambda figure, *args, **kwargs: figures.append(figure),
    )
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = df.copy(deep=True)
    at.session_state["source"] = "chart test fixture"
    at.run()
    assert not at.exception
    at.switch_page(CHARTS_PAGE).run()
    assert not at.exception
    assert figures
    return at, figures


def _set_selectbox(at, key, value):
    at.selectbox(key=key).set_value(value).run()
    assert not at.exception


def _trace_values(figure):
    return {
        trace.name: (
            list(trace.x) if trace.x is not None else [],
            list(trace.y) if trace.y is not None else [],
        )
        for trace in figure.data
    }


def test_bar_chart_count_sum_average_and_median_use_expected_group_results(monkeypatch):
    df = pd.DataFrame(
        {
            "Category": ["A", "A", "A", "B", "B"],
            "Amount": [1.0, 3.0, 9.0, 2.0, 6.0],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    count_trace = figures[-1].data[0]
    assert count_trace.type == "bar"
    assert list(count_trace.x) == ["A", "B"]
    assert list(count_trace.y) == [3, 2]
    assert "Count of rows" in at.selectbox(key="w_Bar_y").options

    _set_selectbox(at, "w_Bar_y", "Amount")
    assert at.selectbox(key="w_Bar_agg").value == "Sum"
    assert list(figures[-1].data[0].y) == [13.0, 8.0]

    _set_selectbox(at, "w_Bar_agg", "Average")
    np.testing.assert_allclose(list(figures[-1].data[0].y), [13 / 3, 4.0])

    _set_selectbox(at, "w_Bar_agg", "Median")
    assert list(figures[-1].data[0].y) == [3.0, 4.0]


def test_count_rows_sentinel_restores_after_leaving_and_reopening_charts(monkeypatch):
    df = pd.DataFrame(
        {
            "Category": ["A", "A", "B"],
            "Sales": [10, 20, 30],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_Bar_y", "Count of rows")
    assert getattr(at.selectbox(key="w_Bar_y").value, "name", None) == "COUNT_ROWS"
    assert list(figures[-1].data[0].y) == [2, 1]

    at.switch_page("Data_Explorer.py").run()
    assert not at.exception
    assert "w_Bar_y" not in at.session_state

    at.switch_page(CHARTS_PAGE).run()
    assert not at.exception
    assert getattr(at.selectbox(key="w_Bar_y").value, "name", None) == "COUNT_ROWS"
    assert list(figures[-1].data[0].y) == [2, 1]

    _set_selectbox(at, "w_Bar_y", "Sales")
    assert list(figures[-1].data[0].y) == [30, 30]
    at.switch_page("Data_Explorer.py").run()
    assert not at.exception
    at.switch_page(CHARTS_PAGE).run()
    assert not at.exception
    assert at.selectbox(key="w_Bar_y").value == "Sales"
    assert list(figures[-1].data[0].y) == [30, 30]


def test_bar_color_grouping_produces_separate_aggregated_series(monkeypatch):
    df = pd.DataFrame(
        {
            "Category": ["A", "A", "B", "B", "A"],
            "Region": ["East", "West", "East", "West", None],
            "Amount": [2, 3, 5, 7, 11],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_Bar_y", "Amount")
    _set_selectbox(at, "w_Bar_color", "Region")

    figure = figures[-1]
    assert at.selectbox(key="w_Bar_mode").value == "Grouped"
    assert figure.layout.barmode == "group"
    assert _trace_values(figure) == {
        "East": (["A", "B"], [2, 5]),
        "West": (["A", "B"], [3, 7]),
    }

    _set_selectbox(at, "w_Bar_mode", "Stacked")
    assert figures[-1].layout.barmode == "stack"
    assert _trace_values(figures[-1]) == {
        "East": (["A", "B"], [2, 5]),
        "West": (["A", "B"], [3, 7]),
    }


def test_grouped_and_stacked_count_keep_color_segments_and_missing_row_feedback(monkeypatch):
    df = pd.DataFrame(
        {
            "Category": ["A", "A", "A", "A", "B", "B", None],
            "Region": ["East", "East", "West", None, "East", "West", "East"],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_Bar_color", "Region")
    grouped_figure = figures[-1]
    grouped_data = _trace_values(grouped_figure)
    assert grouped_figure.layout.barmode == "group"
    assert grouped_data == {
        "East": (["A", "B"], [2, 1]),
        "West": (["A", "B"], [1, 1]),
    }
    assert any("2 rows excluded" in item.value for item in at.caption)

    _set_selectbox(at, "w_Bar_mode", "Stacked")
    stacked_figure = figures[-1]
    assert stacked_figure.layout.barmode == "stack"
    assert _trace_values(stacked_figure) == grouped_data


def test_reserved_labels_coexist_with_sentinel_choices_and_select_real_columns(monkeypatch):
    df = pd.DataFrame(
        {
            "Category": ["A", "A", "B", "B"],
            "(none)": ["red", "blue", "red", "blue"],
            "Count of rows": [10, 20, 30, 40],
            "Amount": [1, 2, 3, 4],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    y_widget = at.selectbox(key="w_Bar_y")
    color_widget = at.selectbox(key="w_Bar_color")
    assert "Count of rows" in y_widget.options
    assert "Count of rows (str, column 3)" in y_widget.options
    assert "(none)" in color_widget.options
    assert "(none) (str, column 2)" in color_widget.options
    assert getattr(y_widget.value, "name", None) == "COUNT_ROWS"
    assert getattr(color_widget.value, "name", None) == "NO_COLOR"

    _set_selectbox(at, "w_Bar_y", "Count of rows")
    assert list(figures[-1].data[0].y) == [30, 70]

    _set_selectbox(at, "w_Bar_y", "Amount")
    _set_selectbox(at, "w_Bar_color", "(none)")
    assert _trace_values(figures[-1]) == {
        "blue": (["A", "B"], [2, 4]),
        "red": (["A", "B"], [1, 3]),
    }


def test_bar_top_n_keeps_and_orders_the_largest_categories(monkeypatch):
    counts = {"A": 1, "B": 6, "C": 5, "D": 4, "E": 3, "F": 2}
    df = pd.DataFrame(
        {"Category": [category for category, count in counts.items() for _ in range(count)]}
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_Bar_topn", 5)

    figure = figures[-1]
    assert set(figure.data[0].x) == {"B", "C", "D", "E", "F"}
    assert list(figure.layout.xaxis.categoryarray) == ["B", "C", "D", "E", "F"]
    assert list(figure.data[0].y) == [6, 5, 4, 3, 2]


def test_stacked_bar_top_n_keeps_orders_and_stacks_largest_categories(monkeypatch):
    counts = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}
    rows = [
        (category, "East" if index % 2 == 0 else "West", 1)
        for category, count in counts.items()
        for index in range(count)
    ]
    df = pd.DataFrame(rows, columns=["Category", "Region", "Amount"])
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_Bar_y", "Amount")
    _set_selectbox(at, "w_Bar_color", "Region")
    _set_selectbox(at, "w_Bar_mode", "Stacked")
    _set_selectbox(at, "w_Bar_topn", 5)

    figure = figures[-1]
    assert figure.layout.barmode == "stack"
    assert list(figure.layout.xaxis.categoryarray) == ["F", "E", "D", "C", "B"]
    assert {trace.name: dict(zip(trace.x, trace.y)) for trace in figure.data} == {
        "East": {"B": 1, "C": 2, "D": 2, "E": 3, "F": 3},
        "West": {"B": 1, "C": 1, "D": 2, "E": 2, "F": 3},
    }


def test_stacked_average_and_median_show_subgroup_statistics_note(monkeypatch):
    df = pd.DataFrame(
        {
            "Category": ["A", "A", "A", "A", "B", "B"],
            "Region": ["East", "East", "East", "West", "East", "West"],
            "Amount": [2, 4, 30, 10, 6, 30],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_Bar_y", "Amount")
    _set_selectbox(at, "w_Bar_color", "Region")
    _set_selectbox(at, "w_Bar_mode", "Stacked")
    note = (
        "The stacked height represents the sum of subgroup "
        "averages/medians, not the overall category average/median."
    )

    _set_selectbox(at, "w_Bar_agg", "Average")
    assert figures[-1].layout.barmode == "stack"
    assert _trace_values(figures[-1]) == {
        "East": (["A", "B"], [12.0, 6.0]),
        "West": (["A", "B"], [10.0, 30.0]),
    }
    assert any(note in item.value for item in at.info)

    _set_selectbox(at, "w_Bar_agg", "Median")
    assert figures[-1].layout.barmode == "stack"
    assert _trace_values(figures[-1]) == {
        "East": (["A", "B"], [4.0, 6.0]),
        "West": (["A", "B"], [10.0, 30.0]),
    }
    assert any(note in item.value for item in at.info)

    _set_selectbox(at, "w_Bar_mode", "Grouped")
    assert figures[-1].layout.barmode == "group"
    assert not any(note in item.value for item in at.info)


def test_stacked_bar_mode_restores_after_navigation(monkeypatch):
    df = pd.DataFrame(
        {
            "Category": ["A", "A", "B", "B"],
            "Region": ["East", "West", "East", "West"],
            "Amount": [2, 3, 5, 7],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    assert at.selectbox(key="w_Bar_mode").value == "Grouped"
    _set_selectbox(at, "w_Bar_mode", "Stacked")
    assert figures[-1].layout.barmode == "stack"

    at.switch_page("Data_Explorer.py").run()
    assert not at.exception
    assert "w_Bar_mode" not in at.session_state
    at.switch_page(CHARTS_PAGE).run()
    assert not at.exception
    assert at.selectbox(key="w_Bar_mode").value == "Stacked"
    assert figures[-1].layout.barmode == "stack"


def test_line_chart_groups_timezone_aware_dates_and_colors_by_day(monkeypatch):
    dates = pd.to_datetime(
        [
            "2025-01-01 12:00+02:00",
            "2025-01-02 08:00+02:00",
            "2025-01-02 19:00+02:00",
            "2025-01-02 21:00+02:00",
            "2025-01-03 10:00+02:00",
        ]
    )
    df = pd.DataFrame(
        {
            "Order Date": dates,
            "Region": ["East", "East", "West", "East", "West"],
            "Sales": [10, 20, 30, 26, 40],
        }
    )
    original_dates = df["Order Date"].copy(deep=True)
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_chart_type", "Line")
    _set_selectbox(at, "w_Line_freq", "Day")
    _set_selectbox(at, "w_Line_agg", "Average")
    _set_selectbox(at, "w_Line_color", "Region")

    figure = figures[-1]
    assert all(trace.type == "scatter" for trace in figure.data)
    traces = _trace_values(figure)
    assert traces["East"][1] == [10, 23]
    assert traces["West"][1] == [30, 40]
    assert [pd.Timestamp(value).strftime("%Y-%m-%d") for value in traces["East"][0]] == [
        "2025-01-01",
        "2025-01-02",
    ]
    pdt.assert_series_equal(at.session_state["df"]["Order Date"], original_dates)


def test_scatter_uses_selected_numeric_axes_and_color_groups(monkeypatch):
    df = pd.DataFrame(
        {
            "X": [1, 2, 3, 4],
            "Y": [10, 20, 30, 40],
            "Region": ["East", "West", "East", "West"],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_chart_type", "Scatter")
    _set_selectbox(at, "w_Scatter_x", "X")
    _set_selectbox(at, "w_Scatter_y", "Y")
    _set_selectbox(at, "w_Scatter_color", "Region")

    figure = figures[-1]
    assert all(trace.type == "scatter" for trace in figure.data)
    traces = _trace_values(figure)
    assert traces == {
        "East": ([1, 3], [10, 30]),
        "West": ([2, 4], [20, 40]),
    }


def test_histogram_uses_selected_numeric_column_and_color_groups(monkeypatch):
    df = pd.DataFrame(
        {
            "Amount": [1.0, 2.0, 3.0, 4.0],
            "Region": ["East", "West", "East", "West"],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_chart_type", "Histogram")
    _set_selectbox(at, "w_Histogram_color", "Region")

    figure = figures[-1]
    assert all(trace.type == "histogram" for trace in figure.data)
    assert {trace.name: list(trace.x) for trace in figure.data} == {
        "East": [1.0, 3.0],
        "West": [2.0, 4.0],
    }


def test_shared_filter_changes_the_actual_chart_aggregation(monkeypatch):
    df = pd.DataFrame(
        {
            "Region": ["East", "West", "East"],
            "Category": ["A", "A", "B"],
            "Amount": [10, 100, 20],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    at.multiselect(key="w_filter_cols").set_value([0]).run()
    assert not at.exception
    at.multiselect(key="w_filter_value_0").set_value(["East"]).run()
    assert not at.exception

    figure = figures[-1]
    assert list(figure.data[0].x) == ["A", "B"]
    assert list(figure.data[0].y) == [1, 1]
    assert any(
        "the chart represents 2 of 2 filtered rows"
        in item.value
        for item in at.caption
    )


def test_bar_omits_missing_group_keys_and_keeps_missing_y_as_nan_for_average(monkeypatch):
    df = pd.DataFrame(
        {
            "Category": ["A", "A", "A", None, "B", "C"],
            "Region": ["East", "East", None, "East", "West", "West"],
            "Amount": [10.0, None, 20.0, 30.0, None, 5.0],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_Bar_y", "Amount")
    _set_selectbox(at, "w_Bar_agg", "Average")
    _set_selectbox(at, "w_Bar_color", "Region")

    figure = figures[-1]
    traces = {trace.name: (list(trace.x), list(trace.y)) for trace in figure.data}
    assert traces["East"] == (["A"], [10.0])
    assert traces["West"][0] == ["B", "C"]
    assert pd.isna(traces["West"][1][0])
    assert traces["West"][1][1] == 5.0


def test_bar_sum_keeps_all_missing_groups_missing_and_sums_valid_groups(monkeypatch):
    df = pd.DataFrame(
        {
            "Category": ["A", "A", "B", "B"],
            "Amount": [None, None, 2.0, 3.0],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_Bar_y", "Amount")
    _set_selectbox(at, "w_Bar_agg", "Sum")

    trace = figures[-1].data[0]
    summed = dict(zip(trace.x, trace.y))
    assert pd.isna(summed["A"])
    assert summed["B"] == 5.0
    assert any("2 rows excluded" in item.value for item in at.caption)
    assert any("missing (Y)" in item.value for item in at.caption)


def test_scatter_row_feedback_counts_only_rows_with_complete_chart_fields(monkeypatch):
    df = pd.DataFrame(
        {
            "X": [1.0, None, 3.0, 4.0],
            "Y": [10.0, 20.0, None, 40.0],
            "Region": ["East", "West", "East", None],
        }
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_chart_type", "Scatter")
    _set_selectbox(at, "w_Scatter_x", "X")
    _set_selectbox(at, "w_Scatter_y", "Y")
    _set_selectbox(at, "w_Scatter_color", "Region")

    figure = figures[-1]
    assert len(figure.data) == 1
    assert list(figure.data[0].x) == [1.0]
    assert list(figure.data[0].y) == [10.0]
    assert any("chart represents 1 of 4 filtered rows" in item.value for item in at.caption)
    assert any(
        "3 rows excluded" in item.value and "(X, Y, Color)" in item.value
        for item in at.caption
    )


def test_empty_filtered_data_stops_before_building_another_chart(monkeypatch):
    df = pd.DataFrame(
        {"Category": ["A", "B"], "Amount": [1, 2]}
    )
    at, figures = _open_charts(df, monkeypatch)
    figure_count = len(figures)

    at.multiselect(key="w_filter_cols").set_value([0]).run()
    assert not at.exception
    at.multiselect(key="w_filter_value_0").set_value([]).run()
    assert not at.exception

    assert len(figures) == figure_count + 1
    assert any("No rows match the current filters" in item.value for item in at.info)


def test_all_missing_group_values_show_clear_no_observations_feedback(monkeypatch):
    df = pd.DataFrame(
        {"Category": pd.Series([None, None], dtype="object"), "Amount": [1, 2]}
    )
    at, figures = _open_charts_without_chart(df, monkeypatch)

    assert not at.exception
    assert figures == []
    assert any(
        "No observations remain after excluding rows with missing chart fields (X)."
        in item.value
        for item in at.info
    )


def test_duplicate_column_labels_stop_chart_creation(monkeypatch):
    df = pd.DataFrame([["A", 1], ["B", 2]], columns=["Duplicate", "Duplicate"])
    at, figures = _open_charts_without_chart(df, monkeypatch)

    assert not at.exception
    assert figures == []
    assert any("Filtering is unavailable" in item.value for item in at.warning)
    assert len(at.selectbox) == 0


def _open_charts_without_chart(df, monkeypatch):
    figures = []
    monkeypatch.setattr(
        st,
        "plotly_chart",
        lambda figure, *args, **kwargs: figures.append(figure),
    )
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = df.copy(deep=True)
    at.session_state["source"] = "chart test fixture"
    at.run()
    assert not at.exception
    at.switch_page(CHARTS_PAGE).run()
    assert not at.exception
    return at, figures


def test_bar_chart_distinguishes_integer_and_string_labels_with_same_display(monkeypatch):
    df = pd.DataFrame(
        [
            [2, "red", "A"],
            [3, "blue", "A"],
            [5, "red", "B"],
        ],
        columns=[1, "1", "Group"],
    )
    at, figures = _open_charts(df, monkeypatch)

    # Both options display as "1" without the type-and-position formatter.
    # The selected string label is used as X and integer label 1 as Y.
    _set_selectbox(at, "w_Bar_x", "1")
    _set_selectbox(at, "w_Bar_y", 1)

    figure = figures[-1]
    assert figure.data[0].type == "bar"
    assert dict(zip(figure.data[0].x, figure.data[0].y)) == {
        "blue": 3,
        "red": 7,
    }

    # Select the same visible string column as Color while using a third
    # column for X. This checks the color values are sourced from string "1".
    _set_selectbox(at, "w_Bar_x", "Group")
    _set_selectbox(at, "w_Bar_y", 1)
    _set_selectbox(at, "w_Bar_color", "1")

    figure = figures[-1]
    assert {trace.name: (list(trace.x), list(trace.y)) for trace in figure.data} == {
        "blue": (["A"], [3]),
        "red": (["A", "B"], [2, 5]),
    }
    assert at.session_state["df"].columns.tolist() == [1, "1", "Group"]
    assert type(at.session_state["df"].columns[0]) is int
    assert type(at.session_state["df"].columns[1]) is str


def test_scatter_chart_distinguishes_integer_and_string_numeric_labels(monkeypatch):
    df = pd.DataFrame(
        [
            [1, 10, "East"],
            [2, 20, "West"],
            [3, 30, "East"],
        ],
        columns=[1, "1", "Region"],
    )
    at, figures = _open_charts(df, monkeypatch)

    _set_selectbox(at, "w_chart_type", "Scatter")
    _set_selectbox(at, "w_Scatter_x", 1)
    _set_selectbox(at, "w_Scatter_y", "1")
    _set_selectbox(at, "w_Scatter_color", "Region")

    figure = figures[-1]
    assert {trace.name: (list(trace.x), list(trace.y)) for trace in figure.data} == {
        "East": ([1, 3], [10, 30]),
        "West": ([2], [20]),
    }
    assert at.session_state["df"].columns.tolist() == [1, "1", "Region"]
