import pandas as pd
import pandas.testing as pdt
import pytest

from components.data_quality import (
    _convert_series,
    _fill_value,
    _standardize_series,
    apply_cleaning,
    missing_value_mask,
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


def test_missing_value_mask_recognizes_opted_in_blanks_and_text_tokens_only():
    values = pd.Series(
        ["", " \t\n", "N/A", " n/a ", "NA", "unknown", "value", 1, None, pd.NA],
        dtype=object,
    )

    disabled = missing_value_mask(values)
    enabled = missing_value_mask(
        values,
        treat_blank_strings=True,
        missing_tokens=["N/A"],
    )
    numeric_value = missing_value_mask(
        pd.Series([1, 2, 3]), missing_tokens=["1", "2"]
    )

    assert disabled.tolist() == [False] * 8 + [True, True]
    assert enabled.tolist() == [True, True, True, True, False, False, False, False, True, True]
    assert numeric_value.tolist() == [False, False, False]


def test_profile_dataframe_separates_actual_and_recognized_missing_values():
    df = pd.DataFrame(
        {
            "text": ["", " \t ", " n/a ", "NA", "value", None],
            "number": [1, 2, 3, 4, 5, None],
        }
    )
    original = df.copy(deep=True)

    default_report, _ = profile_dataframe(df)
    report, _ = profile_dataframe(
        df,
        treat_blank_strings=True,
        missing_tokens=["N/A"],
    )

    assert default_report["total_missing"] == 2
    assert default_report["recognized_as_missing"] == 0
    assert report["total_missing"] == 5
    assert report["actual_missing"] == 2
    assert report["recognized_as_missing"] == 3
    assert report["complete_percent"] == 100 * (12 - 5) / 12
    assert report["column_report"][0]["Actual missing"] == 1
    assert report["column_report"][0]["Recognized as missing"] == 3
    assert report["column_report"][0]["Missing"] == 4
    pdt.assert_frame_equal(df, original)


def test_profile_dataframe_recognizes_blank_values_positionally_with_duplicate_labels():
    df = pd.DataFrame(
        [["", None], [" \t ", "N/A"], ["value", "keep"]],
        columns=["repeat", "repeat"],
    )

    report, _ = profile_dataframe(
        df,
        treat_blank_strings=True,
        missing_tokens=["N/A"],
    )

    assert [column["Position"] for column in report["column_report"]] == [1, 2]
    assert [column["Actual missing"] for column in report["column_report"]] == [0, 1]
    assert [column["Recognized as missing"] for column in report["column_report"]] == [2, 1]
    assert report["total_missing"] == 4
    assert report["complete_percent"] == (100 * 2 / 6)


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


def test_preview_and_apply_drop_recognized_blank_like_values_consistently():
    df = pd.DataFrame(
        {
            "label": ["", " \t ", "N/A", " n/a ", "NA", "keep", None],
            "unrelated": ["N/A", "", "keep", "keep", "keep", "keep", "keep"],
        }
    )
    original = df.copy(deep=True)
    settings = {
        "treat_blank_strings": True,
        "missing_tokens": ["N/A"],
        "missing_action": "Drop rows",
        "drop_missing_columns": ["label"],
    }

    summary, preview, _ = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings)

    assert summary["rows_dropped_for_missing"] == 5
    expected = pd.DataFrame(
        {
            "label": ["NA", "keep"],
            "unrelated": ["keep", "keep"],
        },
        index=[4, 5],
    )
    pdt.assert_frame_equal(preview, expected)
    pdt.assert_frame_equal(applied, expected)
    pdt.assert_frame_equal(df, original)


def test_preview_and_apply_fill_recognized_blank_like_values_with_constant():
    df = pd.DataFrame(
        {
            "label": ["", " \t ", "N/A", " n/a ", "NA", "keep", None],
            "unrelated": ["N/A", "", "keep", "keep", "keep", "keep", "keep"],
        }
    )
    original = df.copy(deep=True)
    settings = {
        "treat_blank_strings": True,
        "missing_tokens": ["N/A"],
        "missing_action": "Fill values",
        "fill_columns": ["label"],
        "fill_strategy": "Constant",
        "fill_constant": "filled",
    }

    summary, preview, fill_values = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings, fill_values=fill_values)

    expected = pd.DataFrame(
        {
            "label": ["filled", "filled", "filled", "filled", "NA", "keep", "filled"],
            "unrelated": ["N/A", "", "keep", "keep", "keep", "keep", "keep"],
        }
    )
    assert summary["missing_values_filled"] == {"label": 5}
    assert fill_values == {"label": "filled"}
    pdt.assert_frame_equal(preview, expected)
    pdt.assert_frame_equal(applied, expected)
    pdt.assert_frame_equal(df, original)


@pytest.mark.parametrize(
    ("strategy", "values", "expected_fill"),
    [
        ("Mean", ["2", "", "8", "N/A", "10", None], 20 / 3),
        ("Median", ["2", "", "8", "N/A", "10", None], 8.0),
        ("Mode", ["2", "2", "", "8", "N/A", None], 2),
    ],
)
def test_statistical_fill_excludes_recognized_blank_like_values(
    strategy, values, expected_fill
):
    df = pd.DataFrame({"score": pd.Series(values, dtype=object)})
    original = df.copy(deep=True)
    settings = {
        "conversions": {"score": "Number"},
        "treat_blank_strings": True,
        "missing_tokens": ["N/A"],
        "missing_action": "Fill values",
        "fill_columns": ["score"],
        "fill_strategy": strategy,
    }

    summary, preview, fill_values = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings, fill_values=fill_values)

    assert summary["missing_values_filled"]["score"] == 3
    assert fill_values["score"] == pytest.approx(expected_fill)
    pdt.assert_frame_equal(preview, applied)
    assert applied["score"].isna().sum() == 0
    pdt.assert_frame_equal(df, original)


@pytest.mark.parametrize(
    ("target", "values"),
    [
        (
            "Number",
            ["1", "", " \t ", "N/A", " n/a ", "unknown", "bad", None],
        ),
        (
            "Integer",
            ["1", "", " \t ", "N/A", " n/a ", "unknown", "bad", None],
        ),
        (
            "Date/Time",
            [
                "2025-01-02",
                "",
                " \t ",
                "N/A",
                " n/a ",
                "unknown",
                "bad date",
                None,
            ],
        ),
    ],
)
def test_conversion_diagnostics_exclude_recognized_blank_like_values(target, values):
    df = pd.DataFrame({"value": pd.Series(values, dtype=object)})
    original = df.copy(deep=True)
    settings = {
        "conversions": {"value": target},
        "treat_blank_strings": True,
        "missing_tokens": ["N/A"],
    }

    summary, preview, _ = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings)

    assert summary["conversion_failures"]["value"] == 2
    examples = [
        value
        for group in summary["conversion_failure_details"]["value"]
        for value in group["examples"]
    ]
    assert set(examples) == {"unknown", "bad" if target != "Date/Time" else "bad date"}
    pdt.assert_frame_equal(preview, applied)
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


@pytest.mark.parametrize(
    ("strategy", "expected_numeric", "expected_text", "expected_category"),
    [
        (
            "Forward Fill",
            [pd.NA, 2, 2, 2, 8, 8],
            [pd.NA, "red", "red", "red", "blue", "blue"],
            [None, "red", "red", "blue", "blue", "blue"],
        ),
        (
            "Backward Fill",
            [2, 2, 8, 8, 8, pd.NA],
            ["red", "red", "blue", "blue", "blue", pd.NA],
            ["red", "red", "blue", "blue", None, None],
        ),
    ],
)
def test_directional_fill_handles_types_blank_values_and_preview_consistently(
    strategy, expected_numeric, expected_text, expected_category
):
    df = pd.DataFrame(
        {
            "number": pd.Series([pd.NA, 2, pd.NA, pd.NA, 8, pd.NA], dtype="Int64"),
            "text": pd.Series(["", "red", " \t ", None, "blue", "N/A"]),
            "category": pd.Categorical(
                ["", "red", None, "blue", None, None],
                categories=["", "red", "blue"],
            ),
            "all_missing": pd.Series([None] * 6, dtype=object),
            "untouched": list("abcdef"),
        }
    )
    original = df.copy(deep=True)
    settings = {
        "treat_blank_strings": True,
        "missing_tokens": ["N/A"],
        "missing_action": "Fill values",
        "fill_columns": ["number", "text", "category", "all_missing"],
        "fill_strategy": strategy,
    }

    summary, preview, fill_values = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings, fill_values=fill_values)

    assert summary["missing_values_filled"] == {
        "number": 3,
        "text": 3,
        "category": 3 if strategy == "Forward Fill" else 2,
        "all_missing": 0,
    }
    assert summary["missing_values_remaining"] == {
        "number": 1,
        "text": 1 if strategy == "Backward Fill" else 1,
        "category": 1 if strategy == "Forward Fill" else 2,
        "all_missing": 6,
    }
    pdt.assert_frame_equal(preview, applied)
    pdt.assert_series_equal(applied["number"], pd.Series(expected_numeric, dtype="Int64", name="number"))
    pdt.assert_series_equal(applied["text"], pd.Series(expected_text, name="text"))
    expected_category_series = pd.Series(
        pd.Categorical(expected_category, categories=["", "red", "blue"]),
        name="category",
    )
    pdt.assert_series_equal(applied["category"], expected_category_series)
    assert applied["all_missing"].isna().all()
    assert applied["untouched"].tolist() == list("abcdef")
    pdt.assert_frame_equal(df, original)


def test_backward_fill_preview_uses_values_beyond_sample_boundary():
    values = [None] * 15 + ["later"] + [None, "end"]
    df = pd.DataFrame({"value": values})
    settings = {
        "missing_action": "Fill values",
        "fill_columns": ["value"],
        "fill_strategy": "Backward Fill",
    }

    _, preview, fill_values = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings, fill_values=fill_values)

    pdt.assert_frame_equal(preview, applied.iloc[: len(preview)])
    assert preview["value"].tolist() == ["later"] * 12


def test_drop_columns_threshold_is_inclusive_and_reports_original_positions():
    df = pd.DataFrame(
        {
            "below": [None, 1, 2, 3],
            "equal": [None, None, 2, 3],
            "above": [None, None, None, 3],
            "complete": [0, 1, 2, 3],
        }
    )
    original = df.copy(deep=True)
    settings = {"drop_columns_threshold": 50}

    summary, preview, _ = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings)

    assert summary["column_drop_threshold"] == 50
    assert summary["columns_to_drop"] == [
        {"Position": 2, "Column": "equal", "Label type": "str", "Missing %": 50.0},
        {"Position": 3, "Column": "above", "Label type": "str", "Missing %": 75.0},
    ]
    assert summary["columns_remaining"] == 2
    expected = df[["below", "complete"]]
    pdt.assert_frame_equal(preview, expected)
    pdt.assert_frame_equal(applied, expected)
    pdt.assert_frame_equal(df, original)


@pytest.mark.parametrize(
    ("recognize_blanks", "expected_columns"),
    [(False, ["blank", "actual"]), (True, ["actual"])],
)
def test_drop_columns_threshold_uses_configured_missing_policy(
    recognize_blanks, expected_columns
):
    df = pd.DataFrame(
        {
            "blank": ["", "N/A", "value", "value"],
            "actual": [None, "a", "b", "c"],
            "complete": ["a", "b", "c", "d"],
        }
    )
    settings = {
        "drop_columns_threshold": 50,
        "treat_blank_strings": recognize_blanks,
        "missing_tokens": ["N/A"],
    }

    summary, preview, _ = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings)

    expected = df[expected_columns + ["complete"]]
    pdt.assert_frame_equal(preview, expected)
    pdt.assert_frame_equal(applied, expected)
    assert summary["columns_remaining"] == len(expected_columns) + 1
    if recognize_blanks:
        assert summary["columns_to_drop"][0]["Missing %"] == 50.0
    else:
        assert summary["columns_to_drop"] == []


def test_drop_columns_threshold_supports_duplicate_and_mixed_type_labels_by_position():
    df = pd.DataFrame(
        [
            [None, None, None, "a", "x"],
            ["a", None, 1, "b", "y"],
            ["b", None, 2, "c", "z"],
            ["c", 3, 3, "d", "w"],
        ],
        columns=["dup", "dup", 1, "1", "keep"],
    )
    settings = {"drop_columns_threshold": 50}

    summary, preview, _ = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings)

    assert [row["Position"] for row in summary["columns_to_drop"]] == [2]
    expected = df.iloc[:, [0, 2, 3, 4]]
    pdt.assert_frame_equal(preview, expected)
    pdt.assert_frame_equal(applied, expected)
    assert applied.columns.tolist() == ["dup", 1, "1", "keep"]
    assert type(applied.columns[1]) is int
    assert type(applied.columns[2]) is str


def test_drop_columns_threshold_rejects_zero_rows_and_removing_every_column():
    with pytest.raises(ValueError, match="zero rows"):
        preview_cleaning(pd.DataFrame(columns=["a"]), {"drop_columns_threshold": 50}, None)

    all_missing = pd.DataFrame({"a": [None, None], "b": [pd.NA, pd.NA]})
    with pytest.raises(ValueError, match="every column"):
        preview_cleaning(all_missing, {"drop_columns_threshold": 50}, None)


def test_apply_cleaning_rejects_explicit_deletion_of_every_column_without_mutation():
    df = pd.DataFrame({"left": [1, 2], "right": [3, 4]})
    original = df.copy(deep=True)

    with pytest.raises(ValueError, match="every column"):
        apply_cleaning(df, {}, drop_column_positions=[0, 1])

    pdt.assert_frame_equal(df, original)


def test_apply_cleaning_explicitly_deletes_only_selected_column_position():
    df = pd.DataFrame(
        [["first", "second", "keep"], ["a", "b", "c"]],
        columns=["duplicate", "duplicate", "other"],
    )
    original = df.copy(deep=True)

    cleaned = apply_cleaning(df, {}, drop_column_positions=[1])

    pdt.assert_frame_equal(cleaned, df.iloc[:, [0, 2]])
    pdt.assert_frame_equal(df, original)


def test_apply_cleaning_explicit_partial_deletion_preserves_zero_row_dataframe():
    df = pd.DataFrame(columns=["remove", "keep"])

    cleaned = apply_cleaning(df, {}, drop_column_positions=[0])

    assert cleaned.empty
    assert cleaned.columns.tolist() == ["keep"]


def test_drop_columns_threshold_can_be_combined_with_directional_fill():
    df = pd.DataFrame(
        {"drop": [None, None, 3], "keep": [1.0, None, 3.0]}
    )
    settings = {
        "drop_columns_threshold": 60,
        "missing_action": "Fill values",
        "fill_columns": ["keep"],
        "fill_strategy": "Forward Fill",
    }
    summary, preview, fill_values = preview_cleaning(df, settings, None)
    applied = apply_cleaning(df, settings, fill_values=fill_values)

    expected = pd.DataFrame({"keep": [1.0, 1.0, 3.0]})
    assert summary["columns_to_drop"][0]["Position"] == 1
    pdt.assert_frame_equal(preview, expected)
    pdt.assert_frame_equal(applied, expected)


