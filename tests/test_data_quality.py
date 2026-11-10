import pandas as pd
import pandas.testing as pdt
import pytest

from components.data_quality import (
    _convert_series,
    _fill_value,
    _standardize_series,
    apply_cleaning,
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


def test_preview_reports_invalid_numeric_examples_and_apply_matches_preview():
    df = pd.DataFrame(
        {"amount": pd.Series(["12", "invalid", "34", None], dtype=object)}
    )
    original = df.copy(deep=True)
    settings = {"conversions": {"amount": "Number"}}

    summary, preview, _ = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings)

    assert summary["conversion_failures"] == {"amount": 1}
    details = summary["conversion_failure_details"]["amount"]
    assert details == [
        {
            "reason": "Not a valid number",
            "count": 1,
            "examples": ["invalid"],
            "additional_count": 0,
        }
    ]
    pdt.assert_frame_equal(preview, applied)
    assert summary["conversion_failures"]["amount"] == int(
        (df["amount"].notna() & applied["amount"].isna()).sum()
    )
    pdt.assert_frame_equal(df, original)


def test_preview_reports_invalid_date_examples_and_apply_matches_preview():
    df = pd.DataFrame(
        {"date": pd.Series(["2025-01-02", "not-a-date", None, "2025-04-05"], dtype=object)}
    )
    original = df.copy(deep=True)
    settings = {"conversions": {"date": "Date/Time"}}

    summary, preview, _ = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings)

    assert summary["conversion_failures"] == {"date": 1}
    details = summary["conversion_failure_details"]["date"]
    assert details == [
        {
            "reason": "Could not parse as Date/Time",
            "count": 1,
            "examples": ["not-a-date"],
            "additional_count": 0,
        }
    ]
    pdt.assert_frame_equal(preview, applied)
    assert summary["conversion_failures"]["date"] == int(
        (df["date"].notna() & applied["date"].isna()).sum()
    )
    pdt.assert_frame_equal(df, original)


def test_preview_separates_non_numeric_and_fractional_integer_values():
    df = pd.DataFrame(
        {
            "quantity": pd.Series(
                ["1", "bad", "2.5", "3.0", "inf", None], dtype=object
            )
        }
    )
    original = df.copy(deep=True)
    settings = {"conversions": {"quantity": "Integer"}}

    summary, preview, _ = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings)

    assert summary["conversion_failures"] == {"quantity": 3}
    assert summary["conversion_failure_details"]["quantity"] == [
        {
            "reason": "Not numeric",
            "count": 1,
            "examples": ["bad"],
            "additional_count": 0,
        },
        {
            "reason": "Fractional numeric value (not a whole number)",
            "count": 1,
            "examples": ["2.5"],
            "additional_count": 0,
        },
        {
            "reason": "Non-finite numeric value",
            "count": 1,
            "examples": ["inf"],
            "additional_count": 0,
        },
    ]
    assert summary["conversion_failures"]["quantity"] == int(
        (df["quantity"].notna() & applied["quantity"].isna()).sum()
    )
    expected = pd.DataFrame(
        {"quantity": pd.Series([1, pd.NA, pd.NA, 3, pd.NA, pd.NA], dtype="Int64")}
    )
    pdt.assert_frame_equal(applied, expected)
    assert applied["quantity"].dtype == pd.Int64Dtype()
    pdt.assert_frame_equal(preview, applied)
    pdt.assert_frame_equal(df, original)


def test_preview_shares_integer_example_limit_across_failure_categories():
    values = ["10"]
    for position in range(7):
        values.extend([f"bad-{position}", f"{position}.5", "inf"])
    df = pd.DataFrame({"quantity": pd.Series(values, dtype=object)})
    settings = {"conversions": {"quantity": "Integer"}}

    summary, _, _ = preview_cleaning(df, settings, None)

    assert summary["conversion_failures"]["quantity"] == 21
    details = {
        item["reason"]: item
        for item in summary["conversion_failure_details"]["quantity"]
    }
    assert details["Not numeric"]["count"] == 7
    assert details["Fractional numeric value (not a whole number)"]["count"] == 7
    assert details["Non-finite numeric value"]["count"] == 7
    assert sum(len(item["examples"]) for item in details.values()) == 5
    assert details["Not numeric"]["additional_count"] == 5
    assert (
        details["Fractional numeric value (not a whole number)"]["additional_count"]
        == 5
    )
    assert details["Non-finite numeric value"]["additional_count"] == 6
    assert sum(item["additional_count"] for item in details.values()) == 16


def test_preview_caps_conversion_examples_and_reports_additional_failures():
    values = [f"invalid-{position}" for position in range(8)]
    df = pd.DataFrame({"amount": pd.Series(values, dtype=object)})
    settings = {"conversions": {"amount": "Number"}}

    summary, _, _ = preview_cleaning(df, settings, None)

    assert summary["conversion_failures"]["amount"] == 8
    details = summary["conversion_failure_details"]["amount"]
    assert len(details) == 1
    assert details[0]["count"] == 8
    assert details[0]["examples"] == [
        "invalid-0",
        "invalid-1",
        "invalid-3",
        "invalid-5",
        "invalid-7",
    ]
    assert len(details[0]["examples"]) == 5
    assert details[0]["additional_count"] == 3
    assert all(type(value) is str for value in details[0]["examples"])


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


