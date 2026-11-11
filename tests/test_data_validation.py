from pathlib import Path

import pandas as pd
import pandas.testing as pdt
from streamlit.testing.v1 import AppTest

import components.data_quality as data_quality
from components.data_quality import validate_dataframe


APP_PATH = Path(__file__).resolve().parents[1] / "Data_Explorer.py"
QUALITY_PAGE = "pages/1_Data_Quality.py"


def _open_quality_page(dataframe):
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = dataframe.copy(deep=True)
    at.session_state["source"] = "validation test fixture"
    at.run()
    assert not at.exception
    at.switch_page(QUALITY_PAGE).run()
    assert not at.exception
    return at


def _run_validation(at):
    at.button(key="dq_run_validation").click().run()
    assert not at.exception


def test_validate_clean_dataset_passes_checks_and_preserves_input():
    dataframe = pd.DataFrame(
        {"Name": ["Ada", "Lin"], "Score": [10, 20]}
    )
    before = dataframe.copy(deep=True)

    result = validate_dataframe(dataframe)

    assert result["status"] == "Completed"
    assert result["rows"] == 2
    assert result["columns"] == 2
    assert result["total_missing"] == 0
    assert result["duplicate_rows"] == 0
    assert result["issues"] == []
    assert result["warnings"] == []
    assert len(result["passed_checks"]) == 3
    pdt.assert_frame_equal(dataframe, before)


def test_validate_missing_values_and_blank_like_policy():
    dataframe = pd.DataFrame(
        {"Label": ["Ada", None, "  ", " N/A ", "ok"]},
        dtype=object,
    )
    before = dataframe.copy(deep=True)

    default_result = validate_dataframe(dataframe)
    assert default_result["total_missing"] == 1
    assert default_result["columns_with_missing"] == [
        {"Position": 1, "Column": "Label", "Missing": 1, "Missing %": 20.0}
    ]

    recognized_result = validate_dataframe(
        dataframe,
        treat_blank_strings=True,
        missing_tokens=["N/A"],
    )
    assert recognized_result["total_missing"] == 3
    assert recognized_result["actual_missing"] == 1
    assert recognized_result["recognized_as_missing"] == 2
    assert recognized_result["columns_with_missing"][0]["Missing"] == 3
    assert recognized_result["issues"][0]["check"] == "Missing values"
    pdt.assert_frame_equal(dataframe, before)


def test_validate_duplicate_rows_uses_existing_profile_conventions():
    dataframe = pd.DataFrame(
        {"Group": ["A", "A", "B"], "Value": [1, 1, 2]}
    )

    result = validate_dataframe(dataframe)

    assert result["duplicate_rows"] == 1
    assert any(issue["check"] == "Duplicate rows" for issue in result["issues"])


def test_validate_reports_current_types_and_obvious_mixed_values():
    dataframe = pd.DataFrame(
        {"measure": pd.Series([1, "bad", 3], dtype=object)}
    )

    result = validate_dataframe(dataframe)

    assert result["column_types"] == [
        {
            "Position": 1,
            "Column": "measure",
            "Data type": "object",
            "Potential mismatch": "Mixed values may indicate inconsistent types",
            "Suggested type": "",
        }
    ]
    assert result["warnings"][0]["column"] == "measure"
    assert result["warnings"][0]["check"] == "Potential data type mismatch"


def test_validate_empty_dataset_reports_unassessable_checks():
    dataframe = pd.DataFrame({"amount": pd.Series(dtype="float64")})

    result = validate_dataframe(dataframe)

    assert result["rows"] == 0
    assert result["columns"] == 1
    assert any(issue["check"] == "Dataset size" for issue in result["issues"])
    assert any(warning["check"] == "Missing value check" for warning in result["warnings"])

    no_columns_result = validate_dataframe(pd.DataFrame())
    assert no_columns_result["rows"] == 0
    assert no_columns_result["columns"] == 0
    assert {issue["check"] for issue in no_columns_result["issues"]} == {
        "Dataset size",
        "Dataset structure",
    }


def test_validate_disambiguates_mixed_and_duplicate_column_labels_by_position():
    dataframe = pd.DataFrame(
        [[1, "one", "left", 10], [2, "two", "right", 20]],
        columns=[1, "1", "duplicate", "duplicate"],
    )

    result = validate_dataframe(dataframe)

    assert [column["Column"] for column in result["column_types"]] == [
        "1 (int, column 1)",
        "1 (str, column 2)",
        "duplicate (str, column 3)",
        "duplicate (str, column 4)",
    ]


def test_validation_result_persists_across_navigation_and_completes_stage():
    dataframe = pd.DataFrame({"Category": ["A", "B"], "Value": [1, 2]})
    at = _open_quality_page(dataframe)

    assert "validate" not in at.session_state["guided_workflow"]["completed"]
    _run_validation(at)

    validation = at.session_state["dq_validation"]
    assert validation["data_version"] == at.session_state["data_version"]
    assert validation["result"]["status"] == "Completed"
    assert "validate" in at.session_state["guided_workflow"]["completed"]

    at.switch_page("pages/3_Charts.py").run()
    assert not at.exception
    at.switch_page(QUALITY_PAGE).run()
    assert not at.exception
    assert at.session_state["dq_validation"] == validation
    assert "validate" in at.session_state["guided_workflow"]["completed"]
    pdt.assert_frame_equal(at.session_state["df"], dataframe)


def test_validation_is_invalidated_after_an_editor_cell_change():
    dataframe = pd.DataFrame({"Category": ["A", "B"], "Value": [1, 2]})
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = dataframe.copy(deep=True)
    at.session_state["source"] = "validation editor fixture"
    at.run()
    assert not at.exception
    at.switch_page(QUALITY_PAGE).run()
    assert not at.exception
    _run_validation(at)
    version_before_edit = at.session_state["data_version"]
    assert "validate" in at.session_state["guided_workflow"]["completed"]

    at.switch_page("pages/2_Editor.py").run()
    assert not at.exception
    at.session_state["editor"] = {
        "edited_rows": {0: {"Value": 9}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()

    assert not at.exception
    assert at.session_state["data_version"] == version_before_edit + 1
    assert "dq_validation" not in at.session_state
    assert "validate" not in at.session_state["guided_workflow"]["completed"]
    assert at.session_state["edited_df"].loc[0, "Value"] == 9

    at.switch_page(QUALITY_PAGE).run()
    assert not at.exception
    assert at.session_state["data_version"] == version_before_edit + 1


def test_validation_setting_change_invalidates_result_and_workflow():
    dataframe = pd.DataFrame({"Label": [" ", "N/A", "ok"]}, dtype=object)
    at = _open_quality_page(dataframe)
    _run_validation(at)
    assert at.session_state["dq_validation"]["result"]["total_missing"] == 0

    at.checkbox(key="dq_treat_blank_strings").set_value(True).run()
    assert not at.exception
    assert "dq_validation" not in at.session_state
    assert "validate" not in at.session_state["guided_workflow"]["completed"]

    at.multiselect(key="dq_missing_tokens").set_value(["N/A"]).run()
    assert not at.exception
    _run_validation(at)
    assert at.session_state["dq_validation"]["result"]["total_missing"] == 2


def test_failed_validation_does_not_complete_workflow(monkeypatch):
    def fail_validation(*args, **kwargs):
        raise ValueError("validation failed")

    monkeypatch.setattr(data_quality, "validate_dataframe", fail_validation)
    at = _open_quality_page(pd.DataFrame({"Value": [1, 2]}))

    _run_validation(at)

    assert "dq_validation" not in at.session_state
    assert "validate" not in at.session_state["guided_workflow"]["completed"]
    assert any("validation failed" in error.value for error in at.error)
