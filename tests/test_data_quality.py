import pandas as pd
import pandas.testing as pdt
import pytest

from components.data_quality import (
    _convert_series,
    _fill_value,
    _standardize_series,
    apply_cleaning,
    bump_data_version,
    ensure_data_version,
    preview_cleaning,
    profile_dataframe,
)


def test_profile_dataframe_reports_shape_missingness_duplicates_and_preserves_input():
    df = pd.DataFrame(
        {
            "name": ["A", "B", "A", None],
            "score": [1, None, 1, 4],
        }
    )
    original = df.copy(deep=True)

    report, duplicate_mask = profile_dataframe(df)

    assert report["rows"] == 4
    assert report["columns"] == 2
    assert report["total_missing"] == 2
    assert report["total_cells"] == 8
    assert report["complete_percent"] == 75.0
    assert report["duplicate_rows"] == 1
    assert report["duplicate_error"] is None
    assert duplicate_mask.tolist() == [False, False, True, False]
    assert report["column_report"][0]["Missing"] == 1
    assert report["column_report"][1]["Missing"] == 1
    pdt.assert_frame_equal(df, original)


def test_profile_dataframe_handles_empty_and_zero_cell_frames():
    frames = [
        pd.DataFrame(),
        pd.DataFrame({"empty": pd.Series(dtype="object")}),
        pd.DataFrame(index=range(3)),
    ]

    for df in frames:
        report, duplicate_mask = profile_dataframe(df)

        assert report["total_cells"] == 0
        assert report["complete_percent"] is None
        assert duplicate_mask is not None
        assert len(duplicate_mask) == len(df)


def test_profile_dataframe_reports_all_missing_columns():
    df = pd.DataFrame({"blank": [pd.NA, pd.NA], "value": [1, 2]})

    report, _ = profile_dataframe(df)

    assert report["column_report"][0]["Missing"] == 2
    assert report["column_report"][0]["Non-missing"] == 0
    assert report["column_report"][0]["Complete %"] == 0.0
    assert report["complete_percent"] == 50.0


def test_profile_dataframe_reports_duplicate_column_labels_by_position():
    df = pd.DataFrame([[1, "a"], [None, "b"]], columns=["repeat", "repeat"])

    report, duplicate_mask = profile_dataframe(df)

    assert report["columns"] == 2
    assert [column["Position"] for column in report["column_report"]] == [1, 2]
    assert [column["Column"] for column in report["column_report"]] == ["repeat", "repeat"]
    assert [column["Missing"] for column in report["column_report"]] == [1, 0]
    assert duplicate_mask.tolist() == [False, False]


def test_convert_series_converts_numeric_values_and_coerces_invalid_values():
    values = pd.Series(["12.5", "invalid", None], name="amount")
    original = values.copy(deep=True)

    converted = _convert_series(values, "Number")

    expected = pd.Series([12.5, float("nan"), float("nan")], name="amount")
    pdt.assert_series_equal(converted, expected)
    pdt.assert_series_equal(values, original)


def test_convert_series_parses_dates_and_preserves_missing_values():
    values = pd.Series(["2025/03/04", "not a date", None], name="date")

    converted = _convert_series(values, "Date/Time", date_format="%Y/%m/%d")

    assert pd.api.types.is_datetime64_any_dtype(converted.dtype)
    expected = pd.Series(
        [pd.Timestamp("2025-03-04"), pd.NaT, pd.NaT],
        name="date",
        dtype=converted.dtype,
    )
    pdt.assert_series_equal(converted, expected)


def test_fill_value_validates_boolean_constants():
    values = pd.Series([True, pd.NA], dtype=object, name="active")

    assert _fill_value(values, "Constant", " TRUE ") is True
    assert _fill_value(values, "Constant", "false") is False
    with pytest.raises(ValueError, match="must be true or false"):
        _fill_value(values, "Constant", "yes")


def test_standardize_series_normalizes_text_and_preserves_missing_values():
    values = pd.Series(["  North\t  west ", None, "SOUTH  "], name="region")

    standardized = _standardize_series(
        values,
        {
            "trim": True,
            "collapse_whitespace": True,
            "case": "lowercase",
        },
    )

    expected = pd.Series(["north west", pd.NA, "south"], name="region", dtype="string")
    pdt.assert_series_equal(standardized, expected)


def test_preview_and_apply_remove_duplicates_and_drop_missing_consistently():
    df = pd.DataFrame(
        {
            "key": [1, 1, 2, 3],
            "label": [" Alpha  ", " Alpha  ", " Beta ", None],
            "score": [10, 10, None, 30],
        }
    )
    original = df.copy(deep=True)
    _, duplicate_mask = profile_dataframe(df)
    settings = {
        "remove_duplicates": True,
        "missing_action": "Drop rows",
        "drop_missing_columns": ["label"],
        "standardize_columns": ["label"],
        "text_actions": {
            "enabled": True,
            "trim": True,
            "collapse_whitespace": True,
            "case": "lowercase",
        },
    }

    summary, preview, fill_values = preview_cleaning(df, settings, duplicate_mask)
    applied = apply_cleaning(df, settings, duplicate_mask, fill_values)

    assert summary["rows_before"] == 4
    assert summary["rows_after"] == 2
    assert summary["duplicate_rows_removed"] == 1
    assert summary["rows_dropped_for_missing"] == 1
    assert summary["text_values_changed"]["label"] == 2
    pdt.assert_frame_equal(preview, applied)
    assert applied["key"].tolist() == [1, 2]
    assert applied["label"].tolist() == ["alpha", "beta"]
    pdt.assert_frame_equal(df, original)


def test_preview_and_apply_fill_numeric_missing_values_consistently():
    df = pd.DataFrame({"score": [2.0, None, 6.0]})
    original = df.copy(deep=True)
    settings = {
        "missing_action": "Fill values",
        "fill_columns": ["score"],
        "fill_strategy": "Mean",
    }

    summary, preview, fill_values = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings, fill_values=fill_values)

    assert summary["missing_values_filled"] == {"score": 1}
    assert fill_values["score"] == 4.0
    assert applied["score"].tolist() == [2.0, 4.0, 6.0]
    pdt.assert_frame_equal(preview, applied)
    pdt.assert_frame_equal(df, original)


def test_apply_cleaning_fills_object_boolean_values_as_booleans():
    df = pd.DataFrame({"active": pd.Series([True, None, False], dtype=object)})
    original = df.copy(deep=True)
    settings = {
        "missing_action": "Fill values",
        "fill_columns": ["active"],
        "fill_strategy": "Constant",
        "fill_constant": "true",
    }

    summary, preview, fill_values = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings, fill_values=fill_values)

    expected = pd.DataFrame({"active": pd.Series([True, True, False], dtype="boolean")})
    assert summary["missing_values_filled"] == {"active": 1}
    assert fill_values == {"active": True}
    pdt.assert_frame_equal(preview, expected)
    pdt.assert_frame_equal(applied, expected)
    pdt.assert_frame_equal(df, original)


def test_bump_data_version_increments_and_clears_quality_results():
    active_df = pd.DataFrame({"value": [1]})
    state = {
        "data_version": 2,
        "dq_analysis": {"report": "old"},
        "dq_preview": {"summary": "old"},
    }

    version = bump_data_version(state, active_df)

    assert version == 3
    assert state["data_version"] == 3
    assert state["data_version_df_id"] == id(active_df)
    assert "dq_analysis" not in state
    assert "dq_preview" not in state


def test_ensure_data_version_initializes_state():
    active_df = pd.DataFrame({"value": [1]})
    state = {
        "dq_analysis": {"report": "old"},
        "dq_preview": {"summary": "old"},
    }

    version = ensure_data_version(state, active_df)

    assert version == 1
    assert state["data_version"] == 1
    assert state["data_version_df_id"] == id(active_df)
    assert "dq_analysis" not in state
    assert "dq_preview" not in state


def test_ensure_data_version_does_not_increment_for_same_dataframe():
    active_df = pd.DataFrame({"value": [1]})
    analysis = {"report": "current"}
    preview = {"summary": "current"}
    state = {
        "data_version": 4,
        "data_version_df_id": id(active_df),
        "dq_analysis": analysis,
        "dq_preview": preview,
    }

    version = ensure_data_version(state, active_df)

    assert version == 4
    assert state["dq_analysis"] is analysis
    assert state["dq_preview"] is preview


def test_ensure_data_version_increments_and_invalidates_on_replacement():
    previous_df = pd.DataFrame({"value": [1]})
    active_df = pd.DataFrame({"value": [2]})
    state = {
        "data_version": 4,
        "data_version_df_id": id(previous_df),
        "dq_analysis": {"report": "old"},
        "dq_preview": {"summary": "old"},
    }

    version = ensure_data_version(state, active_df)

    assert version == 5
    assert state["data_version_df_id"] == id(active_df)
    assert "dq_analysis" not in state
    assert "dq_preview" not in state
