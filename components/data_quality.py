"""Data profiling and opt-in cleaning helpers for the Data Quality page."""

from __future__ import annotations

import hashlib
import warnings

import numpy as np
import pandas as pd
from pandas.api import types as ptypes


SAMPLE_SIZE = 500
PREVIEW_ROWS = 12


def bump_data_version(session_state, active_df: pd.DataFrame | None = None) -> int:
    """Record a controlled dataset replacement and discard derived quality results."""
    try:
        version = int(session_state.get("data_version", 0))
    except (TypeError, ValueError):
        version = 0
    version += 1
    session_state["data_version"] = version
    if active_df is not None:
        session_state["data_version_df_id"] = id(active_df)
    session_state.pop("dq_analysis", None)
    session_state.pop("dq_preview", None)
    return version


def ensure_data_version(session_state, active_df: pd.DataFrame) -> int:
    """Notice dataframe replacement by existing pages that assign edited_df."""
    if (
        "data_version" not in session_state
        or session_state.get("data_version_df_id") != id(active_df)
    ):
        return bump_data_version(session_state, active_df)
    return int(session_state["data_version"])


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


def profile_dataframe(df: pd.DataFrame) -> tuple[dict, np.ndarray | None]:
    """Build a compact quality report and cacheable positional duplicate mask."""
    row_count, column_count = df.shape
    column_report = []
    total_missing = 0
    for position, name in enumerate(df.columns):
        series = df.iloc[:, position]
        missing = int(series.isna().sum())
        total_missing += missing
        mismatch, suggestion = _type_candidates(series)
        non_missing = row_count - missing
        column_report.append(
            {
                "Position": position + 1,
                "Column": str(name),
                "Data type": str(series.dtype),
                "Non-missing": non_missing,
                "Missing": missing,
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
        "total_cells": total_cells,
        "complete_percent": complete_percent,
        "duplicate_rows": duplicate_count,
        "duplicate_error": duplicate_error,
        "column_report": column_report,
    }
    return report, duplicate_mask


def _convert_series(series: pd.Series, target: str, date_format: str | None = None) -> pd.Series:
    if target == "Text":
        return series.astype("string")
    if target == "Number":
        return pd.to_numeric(series, errors="coerce")
    if target == "Integer":
        numeric = pd.to_numeric(series, errors="coerce")
        fractional = numeric.notna() & (numeric % 1 != 0)
        return numeric.mask(fractional).astype("Int64")
    if target == "Date/Time":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return pd.to_datetime(series, format=date_format or None, errors="coerce")
    raise ValueError(f"Unsupported target type: {target}")


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
    conversion_failures = {}
    drop_columns = settings.get("drop_missing_columns", [])
    missing_action = settings.get("missing_action", "Leave unchanged")

    for column in set(conversions) | set(drop_columns):
        if column not in df.columns:
            continue
        original = df[column]
        converted = (
            _convert_series(original, conversions[column], date_format)
            if column in conversions
            else original
        )
        if column in conversions:
            conversion_failures[column] = int((original.notna() & converted.isna()).sum())
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
            series = df[column]
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
            series = df[column]
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
    for column, target in conversions.items():
        if column in result.columns:
            result[column] = _convert_series(result[column], target, date_format)

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
                keep_rows &= result[column].notna().to_numpy(dtype=bool)
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
            if values is None and not result[column].isna().any():
                continue
            value = values.get(column) if values is not None else None
            if value is None or pd.isna(value):
                value = _fill_value(
                    result[column],
                    settings.get("fill_strategy", "Mode"),
                    settings.get("fill_constant", ""),
                )
            series = result[column]
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
                result[column] = _standardize_series(result[column], text_actions)

    return result
