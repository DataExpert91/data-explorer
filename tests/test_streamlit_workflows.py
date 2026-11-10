from pathlib import Path

import pandas as pd
import pandas.testing as pdt
from streamlit.testing.v1 import AppTest

from components.data_quality import (
    dataframe_signature,
    preview_cleaning,
    profile_dataframe,
)


APP_PATH = Path(__file__).resolve().parents[1] / "Data_Explorer.py"
QUALITY_PAGE = "pages/1_Data_Quality.py"


def _assert_no_streamlit_exception(at):
    assert not at.exception


def _click_button(at, key):
    at.button(key=key).click().run()
    _assert_no_streamlit_exception(at)


def _open_quality_page(df, edited_df=None):
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = df.copy(deep=True)
    at.session_state["source"] = "test fixture"
    if edited_df is not None:
        at.session_state["edited_df"] = edited_df.copy(deep=True)

    at.run()
    _assert_no_streamlit_exception(at)
    at.switch_page(QUALITY_PAGE).run()
    _assert_no_streamlit_exception(at)
    return at


def _apply_duplicate_removal(at):
    _click_button(at, "dq_run_analysis")
    assert "dq_analysis" in at.session_state

    at.checkbox(key="dq_remove_duplicates").set_value(True).run()
    _assert_no_streamlit_exception(at)

    _click_button(at, "dq_run_preview")
    assert "dq_preview" in at.session_state

    version_before_apply = at.session_state["data_version"]
    _click_button(at, "dq_apply_cleaning")
    return version_before_apply


def test_apply_and_undo_when_no_edited_dataframe_exists_initially():
    original_df = pd.DataFrame(
        {"Group": ["A", "A", "B"], "Value": [1, 1, 2]}
    )
    expected_cleaned = pd.DataFrame(
        {"Group": ["A", "B"], "Value": [1, 2]}, index=[0, 2]
    )
    at = _open_quality_page(original_df)

    version_before_apply = _apply_duplicate_removal(at)

    pdt.assert_frame_equal(at.session_state["edited_df"], expected_cleaned)
    assert at.session_state["dq_undo"]["had_edited_df"] is False
    pdt.assert_frame_equal(at.session_state["dq_undo"]["previous_df"], original_df)
    assert at.session_state["data_version"] == version_before_apply + 1
    assert at.session_state["data_version_df_id"] == id(at.session_state["edited_df"])
    assert "dq_analysis" not in at.session_state
    assert "dq_preview" not in at.session_state

    version_before_undo = at.session_state["data_version"]
    _click_button(at, "dq_undo_cleaning")

    assert "edited_df" not in at.session_state
    assert "dq_undo" not in at.session_state
    pdt.assert_frame_equal(at.session_state["df"], original_df)
    assert at.session_state["data_version"] == version_before_undo + 1
    assert at.session_state["data_version_df_id"] == id(at.session_state["df"])
    assert "dq_analysis" not in at.session_state
    assert "dq_preview" not in at.session_state


def test_apply_and_undo_restore_an_existing_edited_dataframe():
    df = pd.DataFrame({"Source": ["source row"]})
    original_edited_df = pd.DataFrame(
        {"Group": ["X", "X", "Y"], "Value": [10, 10, 20]},
        index=[5, 6, 7],
    )
    expected_cleaned = pd.DataFrame(
        {"Group": ["X", "Y"], "Value": [10, 20]}, index=[5, 7]
    )
    at = _open_quality_page(df, edited_df=original_edited_df)

    version_before_apply = _apply_duplicate_removal(at)

    pdt.assert_frame_equal(at.session_state["edited_df"], expected_cleaned)
    assert at.session_state["dq_undo"]["had_edited_df"] is True
    pdt.assert_frame_equal(
        at.session_state["dq_undo"]["previous_df"], original_edited_df
    )
    assert at.session_state["data_version"] == version_before_apply + 1

    version_before_undo = at.session_state["data_version"]
    _click_button(at, "dq_undo_cleaning")

    assert "edited_df" in at.session_state
    pdt.assert_frame_equal(at.session_state["edited_df"], original_edited_df)
    assert "dq_undo" not in at.session_state
    assert at.session_state["data_version"] == version_before_undo + 1
    assert at.session_state["data_version_df_id"] == id(at.session_state["edited_df"])


def test_undo_button_availability_tracks_the_undo_snapshot():
    df = pd.DataFrame({"Group": ["A", "A", "B"], "Value": [1, 1, 2]})
    at = _open_quality_page(df)

    assert at.button(key="dq_undo_cleaning").disabled

    _apply_duplicate_removal(at)
    assert "dq_undo" in at.session_state
    assert not at.button(key="dq_undo_cleaning").disabled

    _click_button(at, "dq_undo_cleaning")
    assert "dq_undo" not in at.session_state
    assert at.button(key="dq_undo_cleaning").disabled


def test_conversion_preview_displays_failures_and_invalidates_when_settings_change():
    df = pd.DataFrame(
        {"amount": pd.Series(["1", "invalid", "2.5", "4"], dtype=object)}
    )
    at = _open_quality_page(df)

    _click_button(at, "dq_run_analysis")
    at.multiselect(key="dq_convert_columns").set_value(["amount"]).run()
    _assert_no_streamlit_exception(at)
    target_key = "dq_target_type_'amount'"
    at.selectbox(key=target_key).set_value("Number").run()
    _assert_no_streamlit_exception(at)

    _click_button(at, "dq_run_preview")
    summary = at.session_state["dq_preview"]["summary"]
    assert summary["conversion_failures"] == {"amount": 1}
    failure_table = next(
        frame.value
        for frame in at.dataframe
        if "Failure reason" in frame.value.columns
    )
    assert failure_table.iloc[0]["Failure reason"] == "Not a valid number"
    assert failure_table.iloc[0]["Total failed conversions"] == 1
    assert "str: 'invalid'" == failure_table.iloc[0]["Original examples"]
    assert not at.button(key="dq_apply_cleaning").disabled

    at.selectbox(key=target_key).set_value("Integer").run()
    _assert_no_streamlit_exception(at)
    assert "dq_preview" not in at.session_state
    assert at.button(key="dq_apply_cleaning").disabled

    _click_button(at, "dq_run_preview")
    summary = at.session_state["dq_preview"]["summary"]
    assert summary["conversion_failures"] == {"amount": 2}
    reasons = {
        detail["reason"]
        for detail in summary["conversion_failure_details"]["amount"]
    }
    assert reasons == {
        "Not numeric",
        "Fractional numeric value (not a whole number)",
    }
    assert not at.button(key="dq_apply_cleaning").disabled

    _click_button(at, "dq_apply_cleaning")
    expected = pd.DataFrame(
        {"amount": pd.Series([1, pd.NA, pd.NA, 4], dtype="Int64")}
    )
    pdt.assert_frame_equal(at.session_state["edited_df"], expected)


def test_conversion_preview_indicates_failures_omitted_from_examples():
    df = pd.DataFrame(
        {"amount": pd.Series([f"invalid-{i}" for i in range(8)], dtype=object)}
    )
    at = _open_quality_page(df)

    _click_button(at, "dq_run_analysis")
    at.multiselect(key="dq_convert_columns").set_value(["amount"]).run()
    _assert_no_streamlit_exception(at)
    at.selectbox(key="dq_target_type_'amount'").set_value("Number").run()
    _assert_no_streamlit_exception(at)
    _click_button(at, "dq_run_preview")

    failure_table = next(
        frame.value
        for frame in at.dataframe
        if "Failure reason" in frame.value.columns
    )
    row = failure_table.iloc[0]
    assert row["Total failed conversions"] == 8
    assert "more not shown" in row["Original examples"]
    assert row["Original examples"].count("str:") == 5


def test_old_conversion_preview_format_is_invalidated_safely():
    df = pd.DataFrame(
        {"amount": pd.Series(["1", "invalid", "3"], dtype=object)}
    )
    at = _open_quality_page(df)

    _click_button(at, "dq_run_analysis")
    at.multiselect(key="dq_convert_columns").set_value(["amount"]).run()
    _assert_no_streamlit_exception(at)
    at.selectbox(key="dq_target_type_'amount'").set_value("Number").run()
    _assert_no_streamlit_exception(at)
    _click_button(at, "dq_run_preview")

    old_preview = dict(at.session_state["dq_preview"])
    old_summary = dict(old_preview["summary"])
    old_summary.pop("conversion_failure_details")
    old_preview["summary"] = old_summary
    old_preview.pop("format_version")
    at.session_state["dq_preview"] = old_preview

    at.run()

    _assert_no_streamlit_exception(at)
    assert "dq_preview" not in at.session_state
    assert at.button(key="dq_apply_cleaning").disabled


def test_blank_recognition_changes_invalidate_analysis_and_preview():
    df = pd.DataFrame(
        {"label": ["", "", "value"], "value": [1, 1, 2]}
    )
    at = _open_quality_page(df)

    _click_button(at, "dq_run_analysis")
    at.checkbox(key="dq_remove_duplicates").set_value(True).run()
    _assert_no_streamlit_exception(at)
    _click_button(at, "dq_run_preview")
    assert "dq_preview" in at.session_state

    at.checkbox(key="dq_treat_blank_strings").set_value(True).run()
    _assert_no_streamlit_exception(at)
    assert "dq_analysis" not in at.session_state
    assert "dq_preview" not in at.session_state
    assert at.button(key="dq_apply_cleaning").disabled

    _click_button(at, "dq_run_analysis")
    assert at.session_state["dq_analysis"]["report"]["total_missing"] == 2
    assert at.session_state["dq_analysis"]["report"]["recognized_as_missing"] == 2
    _click_button(at, "dq_run_preview")
    assert "dq_preview" in at.session_state

    at.multiselect(key="dq_missing_tokens").set_value(["N/A"]).run()
    _assert_no_streamlit_exception(at)
    assert "dq_analysis" not in at.session_state
    assert "dq_preview" not in at.session_state
    assert at.button(key="dq_apply_cleaning").disabled


def test_conversion_failure_report_distinguishes_same_string_column_labels():
    df = pd.DataFrame(
        [["bad-integer-label", "bad-string-label"], ["1", "2"]],
        columns=[1, "1"],
    )
    at = _open_quality_page(df)

    _click_button(at, "dq_run_analysis")
    at.multiselect(key="dq_convert_columns").set_value([1]).run()
    _assert_no_streamlit_exception(at)
    at.selectbox(key="dq_target_type_1").set_value("Number").run()
    _assert_no_streamlit_exception(at)
    _click_button(at, "dq_run_preview")

    # Streamlit displays these two option labels identically in a multiselect.
    # Generate both real conversion details directly to verify the report's
    # typed labels without relying on ambiguous option selection in AppTest.
    combined_summary, _, _ = preview_cleaning(
        at.session_state["df"],
        {"conversions": {1: "Number", "1": "Number"}},
        at.session_state["dq_analysis"]["duplicate_mask"],
    )
    preview_state = dict(at.session_state["dq_preview"])
    preview_state["summary"] = combined_summary
    at.session_state["dq_preview"] = preview_state
    at.run()
    _assert_no_streamlit_exception(at)

    failure_table = next(
        frame.value
        for frame in at.dataframe
        if "Failure reason" in frame.value.columns
    )
    assert failure_table["Column"].tolist() == [
        "1 (int, column 1)",
        "1 (str, column 2)",
    ]
    assert at.session_state["df"].columns.tolist() == [1, "1"]
    assert type(at.session_state["df"].columns[0]) is int
    assert type(at.session_state["df"].columns[1]) is str


def test_new_csv_upload_clears_old_quality_and_edit_state():
    old_df = pd.DataFrame({"Category": ["Old"], "Amount": [1]})
    old_edited_df = pd.DataFrame({"Category": ["Edited"], "Amount": [2]})
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = old_df.copy(deep=True)
    at.session_state["edited_df"] = old_edited_df.copy(deep=True)
    at.session_state["source"] = "old.csv"
    at.session_state["data_version"] = 6
    at.session_state["data_version_df_id"] = id(at.session_state["edited_df"])
    at.session_state["dq_analysis"] = {"report": "stale"}
    at.session_state["dq_preview"] = {"summary": "stale"}
    at.session_state["dq_undo"] = {"previous_df": old_df}
    at.session_state["filters"] = {"Category": ["Edited"]}
    at.session_state["filter_cols"] = ["Category"]
    at.session_state["w_filter_cols"] = [0]

    at.run()
    _assert_no_streamlit_exception(at)
    at.multiselect(key="w_filter_value_0").set_value(["Edited"]).run()
    _assert_no_streamlit_exception(at)
    assert at.session_state["w_filter_value_0"] == ["Edited"]
    version_before_upload = at.session_state["data_version"]

    at.file_uploader[0].set_value(
        ("new.csv", b"Region,Amount\nNorth,10\nSouth,20\n", "text/csv")
    ).run()
    _assert_no_streamlit_exception(at)

    expected_df = pd.DataFrame({"Region": ["North", "South"], "Amount": [10, 20]})
    pdt.assert_frame_equal(at.session_state["df"], expected_df)
    assert at.session_state["source"] == "new.csv"
    assert at.session_state["data_version"] == version_before_upload + 1
    assert at.session_state["data_version_df_id"] == id(at.session_state["df"])
    assert "edited_df" not in at.session_state
    assert "dq_analysis" not in at.session_state
    assert "dq_preview" not in at.session_state
    assert "dq_undo" not in at.session_state

    # Filter state is cleared, then recreated for the newly uploaded columns.
    assert at.session_state["filters"] == {}
    assert at.session_state["filter_cols"] == []
    assert at.session_state["w_filter_cols"] == []
    assert "w_filter_value_0" not in at.session_state
