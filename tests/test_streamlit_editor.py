from pathlib import Path

import json

import pandas as pd
import pandas.testing as pdt
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "Data_Explorer.py"
EDITOR_PAGE = "pages/2_Editor.py"


def _open_editor(df, protected_columns=None):
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = df.copy(deep=True)
    at.session_state["source"] = "editor test fixture"
    if protected_columns is not None:
        at.session_state["protected_cols"] = protected_columns
    at.run()
    assert not at.exception

    at.switch_page(EDITOR_PAGE).run()
    assert not at.exception
    return at


def _delete_column_positions(at, positions):
    at.multiselect(key="w_delete_column_positions").set_value(positions)
    at.button(key="delete_columns_submit").click().run()
    assert not at.exception


def test_editor_renders_mixed_type_column_labels_without_changing_source():
    df = pd.DataFrame(
        [[10, "left"], [20, "right"]],
        columns=[1, "1"],
    )
    assert df.columns.is_unique

    at = _open_editor(df)

    assert len(at.data_editor) == 1
    assert at.data_editor[0].value.columns.tolist() == ["col_0", "col_1"]
    pdt.assert_frame_equal(at.session_state["df"], df)
    pdt.assert_frame_equal(at.session_state["editor_base"], df)
    pdt.assert_frame_equal(at.session_state["edited_df"], df)


def test_editor_restores_original_label_types_after_a_cell_edit():
    df = pd.DataFrame(
        [[10, "left"], [20, "right"]],
        columns=[1, "1"],
    )
    at = _open_editor(df)

    at.session_state["editor"] = {
        "edited_rows": {0: {"col_0": 99}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()

    assert not at.exception
    expected = df.copy(deep=True)
    expected.iloc[0, 0] = 99
    pdt.assert_frame_equal(at.session_state["edited_df"], expected)
    pdt.assert_frame_equal(at.session_state["df"], df)
    pdt.assert_frame_equal(at.session_state["editor_base"], df)
    assert type(at.session_state["edited_df"].columns[0]) is int
    assert type(at.session_state["edited_df"].columns[1]) is str


def test_protected_mixed_type_column_maps_to_its_temporary_editor_label():
    df = pd.DataFrame(
        [[10, "left"], [20, "right"]],
        columns=[1, "1"],
    )
    at = _open_editor(df, protected_columns=[1])

    assert not at.exception
    editor_columns = json.loads(at.data_editor[0].proto.columns)

    assert at.session_state["protected_cols"] == [1]
    assert editor_columns["col_0"]["disabled"] is True
    assert editor_columns.get("col_1", {}).get("disabled") is not True


def test_editor_supports_duplicate_string_column_labels():
    df = pd.DataFrame(
        [["left", 10], ["right", 20]],
        columns=["Duplicate", "Duplicate"],
    )

    at = _open_editor(df)

    assert len(at.data_editor) == 1
    assert at.data_editor[0].value.columns.tolist() == ["col_0", "col_1"]
    pdt.assert_frame_equal(at.session_state["df"], df)

    at.session_state["editor"] = {
        "edited_rows": {0: {"col_1": 99}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()

    assert not at.exception
    expected = df.copy(deep=True)
    expected.iloc[0, 1] = 99
    pdt.assert_frame_equal(at.session_state["edited_df"], expected)
    pdt.assert_frame_equal(at.session_state["df"], df)


def test_delete_first_duplicate_named_column_by_position():
    df = pd.DataFrame(
        [["first-1", "second-1", "keep-1"], ["first-2", "second-2", "keep-2"]],
        columns=["Duplicate", "Duplicate", "Keep"],
    )
    at = _open_editor(df)

    _delete_column_positions(at, [0])

    expected = df.iloc[:, [1, 2]].copy()
    pdt.assert_frame_equal(at.session_state["edited_df"], expected)
    pdt.assert_frame_equal(at.session_state["editor_base"], expected)
    pdt.assert_frame_equal(at.session_state["df"], df)


def test_delete_second_duplicate_named_column_by_position():
    df = pd.DataFrame(
        [["first-1", "second-1", "keep-1"], ["first-2", "second-2", "keep-2"]],
        columns=["Duplicate", "Duplicate", "Keep"],
    )
    at = _open_editor(df)

    _delete_column_positions(at, [1])

    expected = df.iloc[:, [0, 2]].copy()
    pdt.assert_frame_equal(at.session_state["edited_df"], expected)
    pdt.assert_frame_equal(at.session_state["editor_base"], expected)
    pdt.assert_frame_equal(at.session_state["df"], df)


def test_editor_prevents_deleting_the_final_column():
    df = pd.DataFrame({"Only": [1, 2]})
    at = _open_editor(df)

    _delete_column_positions(at, [0])

    assert any("A table needs at least one column." in error.value for error in at.error)
    pdt.assert_frame_equal(at.session_state["edited_df"], df)
    pdt.assert_frame_equal(at.session_state["editor_base"], df)


def test_editor_prevents_deleting_all_duplicate_labeled_columns():
    df = pd.DataFrame([["first", "second"]], columns=["Duplicate", "Duplicate"])
    at = _open_editor(df)

    _delete_column_positions(at, [0, 1])

    assert any("A table needs at least one column." in error.value for error in at.error)
    pdt.assert_frame_equal(at.session_state["edited_df"], df)
    pdt.assert_frame_equal(at.session_state["editor_base"], df)


def test_protected_duplicate_column_is_position_specific_and_other_remains_editable():
    df = pd.DataFrame(
        [["protected", "editable"]],
        columns=["Duplicate", "Duplicate"],
    )
    at = _open_editor(df)

    at.multiselect(key="w_protected_positions").set_value([0]).run()

    assert not at.exception
    editor_columns = json.loads(at.data_editor[0].proto.columns)
    assert at.session_state["w_protected_positions"] == [0]
    assert at.session_state["protected_cols"] == ["Duplicate"]
    assert editor_columns["col_0"]["disabled"] is True
    assert editor_columns.get("col_1", {}).get("disabled") is not True

    at.switch_page("pages/1_Data_Quality.py").run()
    assert not at.exception
    at.switch_page(EDITOR_PAGE).run()
    assert not at.exception
    assert at.session_state["w_protected_positions"] == [0]

    at.session_state["editor"] = {
        "edited_rows": {0: {"col_1": "updated"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()

    expected = pd.DataFrame(
        [["protected", "updated"]],
        columns=["Duplicate", "Duplicate"],
    )
    assert not at.exception
    pdt.assert_frame_equal(at.session_state["edited_df"], expected)
    assert at.session_state["w_protected_positions"] == [0]


def test_position_deletion_preserves_mixed_type_column_labels():
    df = pd.DataFrame(
        [[10, "string one", "keep"], [20, "string two", "also keep"]],
        columns=[1, "1", "Keep"],
    )
    at = _open_editor(df)

    _delete_column_positions(at, [0])

    expected = df.iloc[:, [1, 2]].copy()
    pdt.assert_frame_equal(at.session_state["edited_df"], expected)
    pdt.assert_frame_equal(at.session_state["editor_base"], expected)
    assert type(at.session_state["edited_df"].columns[0]) is str
    assert at.session_state["edited_df"].columns.tolist() == ["1", "Keep"]
    pdt.assert_frame_equal(at.session_state["df"], df)


def test_unique_string_column_labels_remain_visible_in_the_editor():
    df = pd.DataFrame({"Category": ["A"], "Amount": [10]})
    at = _open_editor(df)

    assert not at.exception
    assert at.data_editor[0].value.columns.tolist() == ["Category", "Amount"]

    _delete_column_positions(at, [1])

    expected = pd.DataFrame({"Category": ["A"]})
    pdt.assert_frame_equal(at.session_state["edited_df"], expected)
    pdt.assert_frame_equal(at.session_state["editor_base"], expected)
