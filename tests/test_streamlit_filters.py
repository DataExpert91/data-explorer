from datetime import date
from pathlib import Path

import pandas as pd
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
    at.multiselect(key="w_filter_cols").set_value(columns).run()
    assert not at.exception


def _visible_row_ids(at):
    return at.dataframe[0].value["RowID"].tolist()


def test_categorical_filter_selects_one_category():
    df = pd.DataFrame(
        {
            "RowID": [0, 1, 2, 3],
            "Category": ["Furniture", "Office Supplies", "Technology", "Furniture"],
        }
    )
    at = _open_explorer(df)
    _select_filter_columns(at, ["Category"])

    at.multiselect(key="w_Category").set_value(["Furniture"]).run()
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

    at.multiselect(key="w_Category").set_value(
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

    at.slider(key="w_Sales").set_range(10, 20).run()
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

    at.date_input(key="w_Order Date").set_value(
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
