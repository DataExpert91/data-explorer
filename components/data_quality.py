"""Data profiling and opt-in cleaning helpers for the Data Quality page."""

from __future__ import annotations

import hashlib
import warnings

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from .session_data import bump_data_version, ensure_data_version


SAMPLE_SIZE = 500
PREVIEW_ROWS = 12
CONVERSION_EXAMPLE_LIMIT = 5
COMMON_MISSING_TEXT_TOKENS = ("N/A", "NA", "NULL", "None", "-", "unknown")


def _bounded_value_repr(value) -> str:
    if isinstance(value, str):
        return f"str:{len(value)}:{value[:192]}:{value[-32:]}"
    if isinstance(value, bytes):
        return f"bytes:{len(value)}:{value[:192]!r}:{value[-32:]!r}"
    return repr(value)[:256]


def dataframe_signature(df: pd.DataFrame, data_version: int = 0) -> tuple:
    """Return a lightweight fingerprint for a session's active dataframe."""
    row_count, column_count = df.shape
    if row_count:
        sample_count = min(row_count, 17)
        if sample_count == 1:
            positions = [0]
        else:
            positions = sorted(
                {i * (row_count - 1) // (sample_count - 1) for i in range(sample_count)}
            )
        sample = df.iloc[positions]
        digest = hashlib.sha256()
        for row in sample.itertuples(index=True, name=None):
            for value in row:
                digest.update(_bounded_value_repr(value).encode("utf-8", errors="replace"))
                digest.update(b"\0")
        sample_digest = digest.hexdigest()
    else:
        sample_digest = "empty"

    return (
        data_version,
        id(df),
        (row_count, column_count),
        tuple((type(column).__name__, repr(column)) for column in df.columns),
        tuple(str(dtype) for dtype in df.dtypes),
        sample_digest,
    )


def _sample_positions(length: int, limit: int = SAMPLE_SIZE) -> list[int]:
    if length <= limit:
        return list(range(length))
    if limit <= 1:
        return [0]
    return sorted({i * (length - 1) // (limit - 1) for i in range(limit)})


def _recognized_blank_like_mask(
    series: pd.Series,
    treat_blank_strings: bool = False,
    missing_tokens=(),
) -> np.ndarray:
    """Return a positional mask for opted-in blank strings and text tokens."""
    normalized_tokens = {
        token.strip().lower()
        for token in missing_tokens
        if isinstance(token, str) and token.strip()
    }
    if not treat_blank_strings and not normalized_tokens:
        return np.zeros(len(series), dtype=bool)

    try:
        trimmed = series.str.strip()
    except (AttributeError, TypeError):
        return np.zeros(len(series), dtype=bool)

    recognized = np.zeros(len(series), dtype=bool)
    if treat_blank_strings:
        recognized |= trimmed.eq("").fillna(False).to_numpy(dtype=bool)
    if normalized_tokens:
        recognized |= (
            trimmed.str.lower().isin(normalized_tokens)
            .fillna(False)
            .to_numpy(dtype=bool)
        )
    return recognized


def missing_value_mask(
    series: pd.Series,
    treat_blank_strings: bool = False,
    missing_tokens=(),
) -> np.ndarray:
    """Return a positional mask combining pandas nulls and opted-in text values."""
    actual_missing = series.isna().to_numpy(dtype=bool, copy=False)
    recognized_blank_like = _recognized_blank_like_mask(
        series, treat_blank_strings, missing_tokens
    )
    return actual_missing | recognized_blank_like


def _replace_recognized_blank_like(
    series: pd.Series,
    treat_blank_strings: bool = False,
    missing_tokens=(),
) -> pd.Series:
    """Return a column where recognized non-null strings are represented as NA."""
    recognized = _recognized_blank_like_mask(
        series, treat_blank_strings, missing_tokens
    )
    if recognized.any():
        return series.mask(recognized, pd.NA)
    return series


def _type_candidates(series: pd.Series) -> tuple[str, str]:
    """Suggest likely numeric/date text without coercing the source column."""
    if not (
        ptypes.is_object_dtype(series.dtype)
        or ptypes.is_string_dtype(series.dtype)
        or isinstance(series.dtype, pd.CategoricalDtype)
    ):
        return "", ""

    sample = series.iloc[_sample_positions(len(series))].dropna()
    if sample.empty:
        return "", ""

    try:
        numeric_ratio = pd.to_numeric(sample, errors="coerce").notna().mean()
    except (TypeError, ValueError):
        numeric_ratio = 0.0
    if len(sample) >= 3 and numeric_ratio >= 0.8:
        return "Mostly numeric-looking text", "Number"

    text_sample = sample.astype("string")
    date_shaped = text_sample.str.contains(r"[-/]|[A-Za-z]", regex=True, na=False)
    date_sample = text_sample[date_shaped]
    if len(date_sample) >= 3:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            try:
                parsed_ratio = pd.to_datetime(date_sample, errors="coerce").notna().mean()
            except (TypeError, ValueError, OverflowError):
                parsed_ratio = 0.0
        if parsed_ratio >= 0.8:
            return "Mostly date-looking text", "Date/Time"

    inferred = ptypes.infer_dtype(sample, skipna=True)
    if inferred in {"mixed", "mixed-integer", "mixed-integer-float", "decimal"}:
        return "Mixed values may indicate inconsistent types", ""
    return "", ""


def profile_dataframe(
    df: pd.DataFrame,
    treat_blank_strings: bool = False,
    missing_tokens=(),
) -> tuple[dict, np.ndarray | None]:
    """Build a compact quality report and cacheable positional duplicate mask."""
    row_count, column_count = df.shape
    column_report = []
    total_missing = 0
    total_actual_missing = 0
    total_recognized_missing = 0
    for position, name in enumerate(df.columns):
        series = df.iloc[:, position]
        actual_missing_mask = series.isna().to_numpy(dtype=bool, copy=False)
        recognized_missing_mask = _recognized_blank_like_mask(
            series, treat_blank_strings, missing_tokens
        )
        actual_missing = int(actual_missing_mask.sum())
        recognized_missing = int(recognized_missing_mask.sum())
        missing = actual_missing + recognized_missing
        total_missing += missing
        total_actual_missing += actual_missing
        total_recognized_missing += recognized_missing
        analysis_series = (
            series.mask(recognized_missing_mask, pd.NA)
            if recognized_missing
            else series
        )
        mismatch, suggestion = _type_candidates(analysis_series)
        non_missing = row_count - missing
        column_report.append(
            {
                "Position": position + 1,
                "Column": str(name),
                "Data type": str(series.dtype),
                "Non-missing": non_missing,
                "Missing": missing,
                "Actual missing": actual_missing,
                "Recognized as missing": recognized_missing,
                "Missing %": (100 * missing / row_count) if row_count else 0.0,
                "Complete %": (100 * non_missing / row_count) if row_count else 0.0,
                "Potential mismatch": mismatch,
                "Suggested type": suggestion,
            }
        )

    duplicate_mask = None
    duplicate_error = None
    try:
        duplicate_mask = df.duplicated(keep="first").to_numpy(dtype=bool, copy=True)
        duplicate_count = int(duplicate_mask.sum())
    except (TypeError, ValueError) as exc:
        duplicate_count = None
        duplicate_error = f"Duplicate detection could not be completed: {exc}"

    total_cells = row_count * column_count
    complete_percent = (
        100 * (total_cells - total_missing) / total_cells if total_cells else None
    )
    report = {
        "rows": row_count,
        "columns": column_count,
        "total_missing": total_missing,
        "actual_missing": total_actual_missing,
        "recognized_as_missing": total_recognized_missing,
        "total_cells": total_cells,
        "complete_percent": complete_percent,
        "duplicate_rows": duplicate_count,
        "duplicate_error": duplicate_error,
        "column_report": column_report,
    }
    return report, duplicate_mask


def _convert_series_with_failure_masks(
    series: pd.Series,
    target: str,
    date_format: str | None = None,
) -> tuple[pd.Series, dict[str, pd.Series]]:
    failure_masks = {}
    if target == "Text":
        return series.astype("string"), failure_masks
    if target == "Number":
        converted = pd.to_numeric(series, errors="coerce")
        failure_masks["Not a valid number"] = series.notna() & converted.isna()
        return converted, failure_masks
    if target == "Integer":
        numeric = pd.to_numeric(series, errors="coerce")
        failure_masks["Not numeric"] = series.notna() & numeric.isna()
        fractional_for_conversion = numeric.notna() & (numeric % 1 != 0)
        non_finite = numeric.isin([np.inf, -np.inf]) & fractional_for_conversion
        fractional = fractional_for_conversion & ~non_finite
        failure_masks["Fractional numeric value (not a whole number)"] = fractional
        failure_masks["Non-finite numeric value"] = non_finite
        converted = numeric.mask(fractional_for_conversion).astype("Int64")
        return converted, failure_masks
    if target == "Date/Time":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            converted = pd.to_datetime(
                series, format=date_format or None, errors="coerce"
            )
        failure_masks["Could not parse as Date/Time"] = series.notna() & converted.isna()
        return converted, failure_masks
    raise ValueError(f"Unsupported target type: {target}")


def _convert_series(series: pd.Series, target: str, date_format: str | None = None) -> pd.Series:
    converted, _ = _convert_series_with_failure_masks(series, target, date_format)
    return converted


def _conversion_failure_details(
    series: pd.Series,
    failure_masks: dict[str, pd.Series],
    example_limit: int = CONVERSION_EXAMPLE_LIMIT,
) -> tuple[int, list[dict]]:
    """Summarize failures and keep at most example_limit original values per column."""
    groups = []
    for reason, mask in failure_masks.items():
        count = int(mask.sum())
        if not count:
            continue
        sample_count = min(example_limit, count)
        sample_offsets = set(_sample_positions(count, sample_count))
        candidate_examples = []
        failure_offset = 0
        for position, failed in enumerate(mask.to_numpy(dtype=bool, copy=False)):
            if failed:
                if failure_offset in sample_offsets:
                    candidate_examples.append(series.iloc[position])
                failure_offset += 1
                if failure_offset > max(sample_offsets, default=-1):
                    break
        groups.append(
            {
                "reason": reason,
                "count": count,
                "candidate_examples": candidate_examples,
                "examples": [],
            }
        )

    total_failures = sum(group["count"] for group in groups)
    if not groups or example_limit <= 0:
        return total_failures, [
            {
                "reason": group["reason"],
                "count": group["count"],
                "examples": [],
                "additional_count": group["count"],
            }
            for group in groups
        ]

    # Give each failure reason an example first, then distribute remaining slots
    # across the reasons so Integer conversions show both kinds when present.
    remaining_slots = example_limit
    for group in groups:
        group["examples"] = group["candidate_examples"][:1]
        remaining_slots -= len(group["examples"])

    while remaining_slots > 0:
        added_example = False
        for group in groups:
            candidate_count = len(group["candidate_examples"])
            if len(group["examples"]) < candidate_count:
                group["examples"].append(
                    group["candidate_examples"][len(group["examples"])]
                )
                remaining_slots -= 1
                added_example = True
                if remaining_slots == 0:
                    break
        if not added_example:
            break

    details = [
        {
            "reason": group["reason"],
            "count": group["count"],
            "examples": group["examples"],
            "additional_count": group["count"] - len(group["examples"]),
        }
        for group in groups
    ]
    return total_failures, details


def _standardize_series(series: pd.Series, actions: dict) -> pd.Series:
    result = series.astype("string")
    if actions.get("trim"):
        result = result.str.strip()
    if actions.get("collapse_whitespace"):
        result = result.str.replace(r"\s+", " ", regex=True)
    case = actions.get("case", "Preserve case")
    if case == "lowercase":
        result = result.str.lower()
    elif case == "Title Case":
        result = result.str.title()
    return result


def _is_boolean_series(series: pd.Series) -> bool:
    if ptypes.is_bool_dtype(series.dtype):
        return True
    if not ptypes.is_object_dtype(series.dtype):
        return False

    found_boolean = False
    for value in series.array:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            continue
        if isinstance(value, (bool, np.bool_)):
            found_boolean = True
        else:
            return False
    return found_boolean


def _fill_value(series: pd.Series, strategy: str, constant: str):
    if _is_boolean_series(series):
        if strategy == "Constant":
            normalized = constant.strip().lower()
            if normalized not in {"true", "false"}:
                raise ValueError(f"The fill value for '{series.name}' must be true or false.")
            return normalized == "true"
        if strategy == "Mode":
            modes = series.astype("boolean").mode(dropna=True)
            if modes.empty:
                raise ValueError(f"Could not determine a fill value for '{series.name}'.")
            return bool(modes.iloc[0])
        raise ValueError(f"Mean/Median fill is not supported for boolean column '{series.name}'.")

    if strategy == "Constant":
        if ptypes.is_numeric_dtype(series.dtype):
            value = pd.to_numeric(pd.Series([constant]), errors="coerce").iloc[0]
            if pd.isna(value):
                raise ValueError(f"The fill value for '{series.name}' must be numeric.")
            if ptypes.is_integer_dtype(series.dtype) and float(value) % 1:
                raise ValueError(f"The fill value for '{series.name}' must be a whole number.")
            return value
        if ptypes.is_datetime64_any_dtype(series.dtype):
            value = pd.to_datetime(constant, errors="coerce")
            if pd.isna(value):
                raise ValueError(f"The fill value for '{series.name}' must be a valid date.")
            return value
        return constant

    if strategy == "Mean":
        if not ptypes.is_numeric_dtype(series.dtype):
            raise ValueError(f"Mean fill requires a numeric column: '{series.name}'.")
        value = series.mean(skipna=True)
    elif strategy == "Median":
        if not ptypes.is_numeric_dtype(series.dtype):
            raise ValueError(f"Median fill requires a numeric column: '{series.name}'.")
        value = series.median(skipna=True)
    elif strategy == "Mode":
        modes = series.mode(dropna=True)
        if modes.empty:
            raise ValueError(f"Could not determine a mode for '{series.name}'.")
        value = modes.iloc[0]
    else:
        raise ValueError(f"Unsupported fill strategy: {strategy}")

    if pd.isna(value):
        raise ValueError(f"Could not determine a fill value for '{series.name}'.")
    return value


def preview_cleaning(
    df: pd.DataFrame,
    settings: dict,
    duplicate_mask: np.ndarray | None,
) -> tuple[dict, pd.DataFrame, dict]:
    """Summarize planned effects and transform only a small sample for display."""
    if settings.get("remove_duplicates") and duplicate_mask is None:
        raise ValueError("Run duplicate detection successfully before removing duplicates.")

    row_count = len(df)
    keep_rows = np.ones(row_count, dtype=bool)
    duplicate_count = 0
    if settings.get("remove_duplicates"):
        if len(duplicate_mask) != row_count:
            raise ValueError("The duplicate results are stale. Run analysis again.")
        duplicate_count = int(duplicate_mask.sum())
        keep_rows &= ~duplicate_mask
    rows_after_duplicates = int(keep_rows.sum())

    conversions = settings.get("conversions", {})
    date_format = settings.get("date_format")
    treat_blank_strings = settings.get("treat_blank_strings", False)
    missing_tokens = settings.get("missing_tokens", ())
    conversion_failures = {}
    conversion_failure_details = {}
    drop_columns = settings.get("drop_missing_columns", [])
    missing_action = settings.get("missing_action", "Leave unchanged")

    for column in set(conversions) | set(drop_columns):
        if column not in df.columns:
            continue
        original = df[column]
        effective_original = _replace_recognized_blank_like(
            original, treat_blank_strings, missing_tokens
        )
        if column in conversions:
            converted, failure_masks = _convert_series_with_failure_masks(
                effective_original, conversions[column], date_format
            )
            failure_count, failure_details = _conversion_failure_details(
                original, failure_masks
            )
            conversion_failures[column] = failure_count
            if failure_details:
                conversion_failure_details[column] = failure_details
        else:
            converted = effective_original
        if missing_action == "Drop rows" and column in drop_columns:
            keep_rows &= converted.notna().to_numpy(dtype=bool)

    rows_after_missing = int(keep_rows.sum())
    dropped_missing = rows_after_duplicates - rows_after_missing

    fill_values = {}
    filled_counts = {}
    if missing_action == "Fill values":
        strategy = settings.get("fill_strategy", "Mode")
        constant = settings.get("fill_constant", "")
        for column in settings.get("fill_columns", []):
            if column not in df.columns:
                continue
            series = _replace_recognized_blank_like(
                df[column], treat_blank_strings, missing_tokens
            )
            if column in conversions:
                series = _convert_series(series, conversions[column], date_format)
            remaining = series if keep_rows.all() else series.iloc[keep_rows]
            missing_count = int(remaining.isna().sum())
            filled_counts[column] = missing_count
            if missing_count:
                fill_values[column] = _fill_value(remaining, strategy, constant)

    standardized_counts = {}
    text_actions = settings.get("text_actions", {})
    if text_actions.get("enabled"):
        for column in settings.get("standardize_columns", []):
            if column not in df.columns:
                continue
            series = _replace_recognized_blank_like(
                df[column], treat_blank_strings, missing_tokens
            )
            if column in conversions:
                series = _convert_series(series, conversions[column], date_format)
            if not keep_rows.all():
                series = series.iloc[keep_rows]
            standardized = _standardize_series(series, text_actions)
            changed = series.astype("string").ne(standardized).fillna(False)
            standardized_counts[column] = int(changed.sum())

    summary = {
        "rows_before": row_count,
        "rows_after": rows_after_missing,
        "duplicate_rows_removed": duplicate_count,
        "rows_dropped_for_missing": dropped_missing,
        "conversion_failures": conversion_failures,
        "conversion_failure_details": conversion_failure_details,
        "missing_values_filled": filled_counts,
        "text_values_changed": standardized_counts,
    }

    sample_length = min(len(df), PREVIEW_ROWS)
    sample_duplicate_mask = duplicate_mask[:sample_length] if duplicate_mask is not None else None
    sample = apply_cleaning(
        df.iloc[:sample_length],
        settings,
        duplicate_mask=sample_duplicate_mask,
        fill_values=fill_values,
    )
    return summary, sample, fill_values


def apply_cleaning(
    df: pd.DataFrame,
    settings: dict,
    duplicate_mask: np.ndarray | None = None,
    fill_values: dict | None = None,
) -> pd.DataFrame:
    """Return a cleaned dataframe without mutating the supplied dataframe."""
    result = df.copy(deep=False)
    conversions = settings.get("conversions", {})
    date_format = settings.get("date_format")
    treat_blank_strings = settings.get("treat_blank_strings", False)
    missing_tokens = settings.get("missing_tokens", ())
    for column, target in conversions.items():
        if column in result.columns:
            series = _replace_recognized_blank_like(
                result[column], treat_blank_strings, missing_tokens
            )
            result[column] = _convert_series(series, target, date_format)

    keep_rows = np.ones(len(result), dtype=bool)
    if settings.get("remove_duplicates"):
        if duplicate_mask is None or len(duplicate_mask) != len(result):
            raise ValueError("Run duplicate detection successfully before removing duplicates.")
        keep_rows &= ~duplicate_mask

    missing_action = settings.get("missing_action", "Leave unchanged")
    if missing_action == "Drop rows":
        columns = [c for c in settings.get("drop_missing_columns", []) if c in result.columns]
        if columns:
            for column in columns:
                if column in conversions:
                    keep_rows &= result[column].notna().to_numpy(dtype=bool)
                else:
                    keep_rows &= ~missing_value_mask(
                        result[column], treat_blank_strings, missing_tokens
                    )
    elif missing_action == "Fill values":
        if settings.get("remove_duplicates") and not keep_rows.all():
            result = result.iloc[keep_rows]
            keep_rows = np.ones(len(result), dtype=bool)
        values = fill_values
        for column in settings.get("fill_columns", []):
            if column not in result.columns:
                continue
            if values is not None and column not in values:
                continue
            series = _replace_recognized_blank_like(
                result[column], treat_blank_strings, missing_tokens
            )
            if values is None and not series.isna().any():
                continue
            value = values.get(column) if values is not None else None
            if value is None or pd.isna(value):
                value = _fill_value(
                    series,
                    settings.get("fill_strategy", "Mode"),
                    settings.get("fill_constant", ""),
                )
            if isinstance(value, (bool, np.bool_)) and ptypes.is_object_dtype(series.dtype):
                series = series.astype("boolean")
            if isinstance(series.dtype, pd.CategoricalDtype) and value not in series.cat.categories:
                series = series.cat.add_categories([value])
            result[column] = series.fillna(value)

    if missing_action != "Fill values" and not keep_rows.all():
        result = result.iloc[keep_rows]

    text_actions = settings.get("text_actions", {})
    if text_actions.get("enabled"):
        for column in settings.get("standardize_columns", []):
            if column in result.columns:
                series = _replace_recognized_blank_like(
                    result[column], treat_blank_strings, missing_tokens
                )
                result[column] = _standardize_series(series, text_actions)

    return result
