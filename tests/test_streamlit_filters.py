from datetime import date
from pathlib import Path

import pandas as pd
import pandas.testing as pdt
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "Data_Explorer.py"


def _open_explorer(df):
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = df.copy(deep=True)
    at.session_state["source"] = "filter test fixture"
    at.run()
    assert not at.exception
    return at


def _select_filter_columns(at, columns):
    current_df = at.session_state.get("edited_df", at.session_state["df"])
    positions = [current_df.columns.get_loc(column) for column in columns]
    at.multiselect(key="w_filter_cols").set_value(positions).run()
    assert not at.exception


def _visible_row_ids(at):
    return at.dataframe[0].value["RowID"].tolist()


def _open_charts_with_filter(at, column, values):
    at.switch_page("pages/3_Charts.py").run()
    assert not at.exception

    current_df = at.session_state.get("edited_df", at.session_state["df"])
    column_position = current_df.columns.get_loc(column)
    at.session_state["filter_cols"] = [column]
    saved_filters = at.session_state.get("filters", {})
    saved_filters[column] = values
    at.session_state["filters"] = saved_filters
    at.session_state["w_filter_cols"] = [column_position]
    at.run()
    assert not at.exception
    return at


def test_categorical_filter_selects_one_category():
    df = pd.DataFrame(
        {
            "RowID": [0, 1, 2, 3],
            "Category": ["Furniture", "Office Supplies", "Technology", "Furniture"],
        }
    )
    at = _open_explorer(df)
    _select_filter_columns(at, ["Category"])

    at.multiselect(key="w_filter_value_1").set_value(["Furniture"]).run()
    assert not at.exception

    assert _visible_row_ids(at) == [0, 3]


def test_categorical_filter_selects_multiple_categories():
    df = pd.DataFrame(
        {
            "RowID": [0, 1, 2, 3],
            "Category": ["Furniture", "Office Supplies", "Technology", "Furniture"],
        }
    )
    at = _open_explorer(df)
    _select_filter_columns(at, ["Category"])

    at.multiselect(key="w_filter_value_1").set_value(
        ["Furniture", "Technology"]
    ).run()
    assert not at.exception

    assert _visible_row_ids(at) == [0, 2, 3]


def test_numeric_filter_includes_range_boundaries_and_excludes_missing_values():
    df = pd.DataFrame(
        {
            "RowID": [0, 1, 2, 3],
            "Sales": [10, 20, 30, None],
        }
    )
    at = _open_explorer(df)
    _select_filter_columns(at, ["Sales"])

    at.slider(key="w_filter_value_1").set_range(10, 20).run()
    assert not at.exception

    assert _visible_row_ids(at) == [0, 1]


def test_date_filter_includes_the_selected_day_and_excludes_nat_rows():
    df = pd.DataFrame(
        {
            "RowID": [0, 1, 2, 3, 4, 5],
            "Order Date": pd.to_datetime(
                [
                    "2025-01-01 23:59:59",
                    "2025-01-02 00:00:00",
                    "2025-01-02 12:34:56",
                    "2025-01-02 23:59:59",
                    "2025-01-03 00:00:00",
                    None,
                ]
            ),
        }
    )
    at = _open_explorer(df)
    _select_filter_columns(at, ["Order Date"])

    at.date_input(key="w_filter_value_1").set_value(
        (date(2025, 1, 2), date(2025, 1, 2))
    ).run()
    assert not at.exception

    assert _visible_row_ids(at) == [1, 2, 3]


def test_single_unique_and_all_missing_numeric_columns_do_not_filter_rows():
    df = pd.DataFrame(
        {
            "RowID": [0, 1, 2],
            "Constant": [7, 7, 7],
            "AllMissing": pd.Series([float("nan")] * 3, dtype="float64"),
        }
    )
    at = _open_explorer(df)
    _select_filter_columns(at, ["Constant", "AllMissing"])

    assert not at.exception
    assert len(at.slider) == 0
    assert _visible_row_ids(at) == [0, 1, 2]


def test_data_explorer_disables_filters_for_duplicate_column_labels():
    df = pd.DataFrame(
        [["A", 1], ["B", 2]],
        columns=["Duplicate", "Duplicate"],
    )

    at = _open_explorer(df)

    assert not at.exception
    assert any(
        "Filtering is unavailable" in warning.value
        and "duplicate column names" in warning.value
        for warning in at.warning
    )
    assert len(at.multiselect) == 0
    assert len(at.slider) == 0
    assert len(at.date_input) == 0
    displayed_df = at.dataframe[0].value
    assert displayed_df.columns.is_unique
    assert displayed_df.to_numpy().tolist() == df.to_numpy().tolist()
    pdt.assert_frame_equal(at.session_state["df"], df)


def test_charts_stops_before_chart_controls_for_duplicate_column_labels():
    df = pd.DataFrame(
        [["A", 1], ["B", 2]],
        columns=["Duplicate", "Duplicate"],
    )
    at = _open_explorer(df)

    at.switch_page("pages/3_Charts.py").run()

    assert not at.exception
    assert any(
        "Filtering is unavailable" in warning.value
        and "duplicate column names" in warning.value
        for warning in at.warning
    )
    assert len(at.multiselect) == 0
    assert len(at.slider) == 0
    assert len(at.date_input) == 0
    assert [widget.key for widget in at.selectbox] == ["language_selector_widget"]


def test_filter_column_named_filter_cols_does_not_collide_with_selector():
    df = pd.DataFrame(
        {
            "RowID": [0, 1, 2],
            "filter_cols": ["keep", "drop", "keep"],
        }
    )
    at = _open_explorer(df)
    _select_filter_columns(at, ["filter_cols"])

    at.multiselect(key="w_filter_value_1").set_value(["keep"]).run()

    assert not at.exception
    assert at.multiselect(key="w_filter_cols").value == [1]
    assert at.multiselect(key="w_filter_value_1").value == ["keep"]
    assert at.session_state["filter_cols"] == ["filter_cols"]
    assert _visible_row_ids(at) == [0, 2]


def test_filter_column_named_chart_type_does_not_collide_on_charts_page():
    df = pd.DataFrame(
        {
            "RowID": [0, 1, 2],
            "chart_type": ["keep", "drop", "keep"],
            "Value": [1, 2, 3],
        }
    )
    at = _open_explorer(df)
    at = _open_charts_with_filter(at, "chart_type", ["keep"])

    assert not at.exception
    assert at.multiselect(key="w_filter_value_1").value == ["keep"]
    assert at.selectbox(key="w_chart_type").value == "Bar"
    assert any("Charts use 2 of 3 rows" in caption.value for caption in at.caption)


def test_filter_column_named_bar_x_does_not_collide_with_chart_axis():
    df = pd.DataFrame(
        {
            "Bar_x": ["keep", "drop", "keep"],
            "Value": [1, 2, 3],
            "RowID": [0, 1, 2],
        }
    )
    at = _open_explorer(df)
    at = _open_charts_with_filter(at, "Bar_x", ["keep"])

    assert not at.exception
    assert at.multiselect(key="w_filter_value_0").value == ["keep"]
    assert at.selectbox(key="w_Bar_x").value == "Bar_x"
    assert any("Charts use 2 of 3 rows" in caption.value for caption in at.caption)


def test_distinct_column_labels_with_same_string_use_independent_filter_state():
    df = pd.DataFrame(
        [
            [0, 10, "keep"],
            [1, 20, "drop"],
            [2, 30, "keep"],
        ],
        columns=["RowID", 1, "1"],
    )
    assert df.columns.is_unique

    at = _open_explorer(df)
    _select_filter_columns(at, [1, "1"])

    at.slider(key="w_filter_value_1").set_range(10, 20).run()
    assert not at.exception
    at.multiselect(key="w_filter_value_2").set_value(["keep"]).run()

    assert not at.exception
    assert at.slider(key="w_filter_value_1").value == (10, 20)
    assert at.multiselect(key="w_filter_value_2").value == ["keep"]
    assert _visible_row_ids(at) == [0]


def test_filter_widget_state_is_cleared_when_column_order_changes():
    df = pd.DataFrame(
        {
            "RowID": [0, 1],
            "Alpha": ["A", "B"],
            "Beta": ["X", "Y"],
        }
    )
    at = _open_explorer(df)
    _select_filter_columns(at, ["Alpha"])
    at.multiselect(key="w_filter_value_1").set_value(["A"]).run()
    assert not at.exception

    reordered_df = df[["RowID", "Beta", "Alpha"]]
    at.session_state["df"] = reordered_df
    at.run()

    assert not at.exception
    assert "w_filter_value_1" not in at.session_state
    assert at.multiselect(key="w_filter_value_2").value == ["A"]
    assert _visible_row_ids(at) == [0]


def test_saved_filter_value_is_cleared_when_column_dtype_changes():
    df = pd.DataFrame(
        {
            "RowID": [0, 1],
            "Amount": [10, 20],
        }
    )
    at = _open_explorer(df)
    _select_filter_columns(at, ["Amount"])
    at.slider(key="w_filter_value_1").set_range(10, 20).run()
    assert not at.exception

    changed_df = df.assign(Amount=["low", "high"])
    at.session_state["df"] = changed_df
    at.run()

    assert not at.exception
    assert len(at.slider) == 0
    assert at.multiselect(key="w_filter_value_1").value == ["high", "low"]
    assert _visible_row_ids(at) == [0, 1]
