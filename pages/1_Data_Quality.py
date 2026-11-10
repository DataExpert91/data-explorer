"""Profile the active dataset and apply optional, reversible cleaning."""

from collections import Counter

import pandas as pd
import streamlit as st
from pandas.api import types as ptypes

from components.data_quality import (
    COMMON_MISSING_TEXT_TOKENS,
    apply_cleaning,
    dataframe_signature,
    preview_cleaning,
    profile_dataframe,
)
from components.session_data import (
    apply_cleaned_dataframe,
    ensure_data_version,
    get_active_dataframe,
    undo_cleaned_dataframe,
)

DQ_PREVIEW_FORMAT_VERSION = 2


st.title("Data Quality")
st.caption(
    "Profile the full active table. Cleaning is previewed first and only published "
    "when you choose Apply."
)

if "df" not in st.session_state:
    st.warning("No data loaded. Please open the main page first.")
    st.stop()

current_df = get_active_dataframe(st.session_state)
ensure_data_version(st.session_state, current_df)
current_signature = dataframe_signature(current_df, st.session_state["data_version"])
has_duplicate_labels = not current_df.columns.is_unique


def invalidate_quality_results():
    """Drop derived results after the active table changes."""
    st.session_state.pop("dq_analysis", None)
    st.session_state.pop("dq_preview", None)


def reset_downstream_widgets():
    """Clear filters, charts, and the Editor widget after a table replacement."""
    for key in (
        "filters",
        "filter_cols",
        "chart_settings",
        "editor",
        "editor_base",
    ):
        st.session_state.pop(key, None)
    for key in list(st.session_state.keys()):
        if key.startswith("w_"):
            del st.session_state[key]


source_name = st.session_state.get("source", "current dataset")
st.caption(f"Current dataset: {source_name}")
st.caption(f"Profiling {len(current_df):,} rows x {len(current_df.columns):,} columns")
if has_duplicate_labels:
    st.warning(
        "This dataset has duplicate column labels. Profiling and exact duplicate-row "
        "analysis are available, but column-targeted cleaning is disabled because "
        "the affected columns cannot be selected unambiguously. Rename the headers "
        "in the source file and upload it again to use those actions."
    )

with st.expander("Blank-like value recognition", expanded=False):
    treat_blank_strings = st.checkbox(
        "Treat empty and whitespace-only strings as missing",
        key="dq_treat_blank_strings",
        help="This applies only to actual text values. It does not change the active data until you apply a cleaning operation.",
    )
    missing_tokens = st.multiselect(
        "Text tokens to treat as missing",
        options=COMMON_MISSING_TEXT_TOKENS,
        key="dq_missing_tokens",
        help="Selected tokens match case-insensitively after surrounding whitespace is trimmed. No tokens are selected by default.",
    )

missing_policy_signature = (
    bool(treat_blank_strings),
    tuple(sorted(token.casefold() for token in missing_tokens)),
)
analysis_signature = (current_signature, missing_policy_signature)

analysis = st.session_state.get("dq_analysis")
if analysis is not None and analysis.get("signature") != analysis_signature:
    invalidate_quality_results()
    analysis = None

column_label_counts = Counter(str(column) for column in current_df.columns)
conversion_column_labels = {}
for position, column in enumerate(current_df.columns):
    label = str(column)
    if column_label_counts[label] > 1 or not isinstance(column, str):
        label = f"{label} ({type(column).__name__}, column {position + 1})"
    conversion_column_labels[column] = label

st.subheader("Quality analysis")
if st.button("Run data quality analysis", key="dq_run_analysis"):
    with st.spinner("Checking completeness, types, and duplicate rows..."):
        try:
            report, duplicate_mask = profile_dataframe(
                current_df,
                treat_blank_strings=treat_blank_strings,
                missing_tokens=missing_tokens,
            )
            st.session_state["dq_analysis"] = {
                "signature": analysis_signature,
                "report": report,
                "duplicate_mask": duplicate_mask,
            }
            st.session_state.pop("dq_preview", None)
            st.rerun()
        except Exception as exc:
            st.error(f"Could not complete the analysis: {exc}")

analysis = st.session_state.get("dq_analysis")
if analysis is None or analysis.get("signature") != analysis_signature:
    st.info("Run the analysis to calculate exact duplicate counts and column statistics.")
else:
    report = analysis["report"]
    metrics = st.columns(4)
    metrics[0].metric("Rows", f"{report['rows']:,}")
    metrics[1].metric("Columns", f"{report['columns']:,}")
    complete_percent = report["complete_percent"]
    metrics[2].metric(
        "Complete cells",
        "N/A" if complete_percent is None else f"{complete_percent:.1f}%",
    )
    if report["duplicate_rows"] is None:
        metrics[3].metric("Duplicate rows", "Unavailable")
    else:
        metrics[3].metric("Duplicate rows", f"{report['duplicate_rows']:,}")

    if report["duplicate_error"]:
        st.warning(report["duplicate_error"])

    column_report = pd.DataFrame(report["column_report"])
    st.dataframe(column_report, use_container_width=True)

    date_candidates = [
        f"{row['Column']} (column {row['Position']})" if has_duplicate_labels else row["Column"]
        for row in report["column_report"]
        if row["Suggested type"] == "Date/Time"
    ]
    if date_candidates:
        st.caption("Potential date columns stored as text: " + ", ".join(date_candidates))
    mismatch_candidates = [
        row for row in report["column_report"] if row["Potential mismatch"]
    ]
    if mismatch_candidates:
        st.caption(
            f"Potential type mismatches found in {len(mismatch_candidates)} column(s). "
            "These are sample-based suggestions; inspect the values before converting."
        )

st.subheader("Cleaning preview")
columns = list(current_df.columns)
cleaning_columns = [] if has_duplicate_labels else columns
valid_values = set(cleaning_columns)


def keep_valid_selection(key, valid_options):
    value = st.session_state.get(key, [])
    if not isinstance(value, list):
        value = []
    cleaned = [item for item in value if item in valid_options]
    if cleaned != value:
        st.session_state[key] = cleaned


keep_valid_selection("dq_convert_columns", valid_values)
convert_columns = st.multiselect(
    "Columns to convert",
    options=cleaning_columns,
    key="dq_convert_columns",
    disabled=has_duplicate_labels,
    help="Choose columns, then select a target type for each one.",
)

target_types = ["Text", "Integer", "Number", "Date/Time"]
report_suggestions = {}
if analysis is not None and analysis.get("signature") == analysis_signature:
    report_suggestions = {
        row["Column"]: row["Suggested type"]
        for row in analysis["report"]["column_report"]
    }

conversions = {}
for column in convert_columns:
    widget_key = f"dq_target_type_{column!r}"
    suggested = report_suggestions.get(str(column), "Text")
    default_target = suggested if suggested in target_types else "Text"
    previous_target = st.session_state.get(widget_key, default_target)
    if previous_target not in target_types:
        st.session_state[widget_key] = default_target
        previous_target = default_target
    conversions[column] = st.selectbox(
        f"Target type for {column}",
        options=target_types,
        index=target_types.index(previous_target),
        key=widget_key,
    )

date_format = None
if any(target == "Date/Time" for target in conversions.values()):
    date_format = st.text_input(
        "Date format (optional)",
        placeholder="For example: %Y-%m-%d",
        key="dq_date_format",
        help="Leave blank to let pandas infer the format.",
    ).strip() or None

remove_duplicates = st.checkbox(
    "Remove exact duplicate rows",
    key="dq_remove_duplicates",
    help="Duplicate rows are identified from the active table before type conversion or text standardization.",
)

missing_actions = ["Leave unchanged", "Drop rows", "Fill values"]
if st.session_state.get("dq_missing_action") not in missing_actions:
    st.session_state["dq_missing_action"] = "Leave unchanged"
missing_action = st.selectbox(
    "Missing value action",
    options=missing_actions,
    key="dq_missing_action",
)

numeric_columns = []
text_columns = []
for position, column in enumerate(cleaning_columns):
    if column in conversions:
        if conversions[column] in {"Integer", "Number"}:
            numeric_columns.append(column)
        elif conversions[column] == "Text":
            text_columns.append(column)
        continue

    dtype = current_df.iloc[:, position].dtype
    if ptypes.is_numeric_dtype(dtype) and not ptypes.is_bool_dtype(dtype):
        numeric_columns.append(column)
    if (
        ptypes.is_object_dtype(dtype)
        or ptypes.is_string_dtype(dtype)
        or isinstance(dtype, pd.CategoricalDtype)
    ):
        text_columns.append(column)

drop_missing_columns = []
fill_columns = []
fill_strategy = "Mode"
fill_constant = ""
if missing_action == "Drop rows":
    keep_valid_selection("dq_drop_missing_columns", valid_values)
    drop_missing_columns = st.multiselect(
        "Drop rows missing values in these columns",
        options=cleaning_columns,
        key="dq_drop_missing_columns",
        disabled=has_duplicate_labels,
        help="Leave this empty to keep all rows.",
    )
elif missing_action == "Fill values":
    fill_strategies = ["Constant", "Mean", "Median", "Mode"]
    if st.session_state.get("dq_fill_strategy") not in fill_strategies:
        st.session_state["dq_fill_strategy"] = "Mode"
    fill_strategy = st.selectbox(
        "Fill strategy",
        options=fill_strategies,
        key="dq_fill_strategy",
    )
    fill_options = numeric_columns if fill_strategy in {"Mean", "Median"} else columns
    keep_valid_selection("dq_fill_columns", set(fill_options))
    fill_columns = st.multiselect(
        "Columns to fill",
        options=fill_options,
        key="dq_fill_columns",
        disabled=has_duplicate_labels,
    )
    if fill_strategy == "Constant":
        fill_constant = st.text_input("Constant fill value", key="dq_fill_constant")

keep_valid_selection("dq_standardize_columns", set(text_columns))
standardize_columns = st.multiselect(
    "Text columns to standardize",
    options=text_columns,
    key="dq_standardize_columns",
    disabled=has_duplicate_labels,
)
text_actions = {"enabled": bool(standardize_columns)}
if standardize_columns:
    text_actions["trim"] = st.checkbox("Trim leading and trailing whitespace", key="dq_trim")
    text_actions["collapse_whitespace"] = st.checkbox(
        "Collapse repeated internal whitespace", key="dq_collapse_whitespace"
    )
    case_options = ["Preserve case", "lowercase", "Title Case"]
    if st.session_state.get("dq_case") not in case_options:
        st.session_state["dq_case"] = "Preserve case"
    text_actions["case"] = st.selectbox(
        "Case normalization", options=case_options, key="dq_case"
    )
else:
    text_actions.update(
        {
            "trim": st.session_state.get("dq_trim", False),
            "collapse_whitespace": st.session_state.get("dq_collapse_whitespace", False),
            "case": st.session_state.get("dq_case", "Preserve case"),
        }
    )

settings = {
    "remove_duplicates": remove_duplicates,
    "conversions": conversions,
    "treat_blank_strings": treat_blank_strings,
    "missing_tokens": list(missing_tokens),
    "date_format": date_format,
    "missing_action": missing_action,
    "drop_missing_columns": drop_missing_columns,
    "fill_columns": fill_columns,
    "fill_strategy": fill_strategy,
    "fill_constant": fill_constant,
    "standardize_columns": standardize_columns,
    "text_actions": text_actions,
}
settings_signature = repr(settings)

preview_state = st.session_state.get("dq_preview")
if preview_state is not None and (
    preview_state.get("data_signature") != current_signature
    or preview_state.get("settings_signature") != settings_signature
    or preview_state.get("format_version") != DQ_PREVIEW_FORMAT_VERSION
):
    st.session_state.pop("dq_preview", None)
    preview_state = None

has_actions = bool(
    remove_duplicates
    or conversions
    or (missing_action == "Drop rows" and drop_missing_columns)
    or (missing_action == "Fill values" and fill_columns)
    or standardize_columns
)
analysis_ready = analysis is not None and analysis.get("signature") == analysis_signature
if st.button(
    "Preview selected cleaning",
    key="dq_run_preview",
    disabled=not analysis_ready or not has_actions,
):
    try:
        summary, sample, fill_values = preview_cleaning(
            current_df,
            settings,
            analysis["duplicate_mask"],
        )
        st.session_state["dq_preview"] = {
            "format_version": DQ_PREVIEW_FORMAT_VERSION,
            "data_signature": current_signature,
            "settings_signature": settings_signature,
            "summary": summary,
            "sample": sample,
            "fill_values": fill_values,
        }
        st.rerun()
    except Exception as exc:
        st.error(f"Could not prepare the preview: {exc}")

preview_state = st.session_state.get("dq_preview")
preview_ready = (
    preview_state is not None
    and preview_state.get("format_version") == DQ_PREVIEW_FORMAT_VERSION
    and preview_state.get("data_signature") == current_signature
    and preview_state.get("settings_signature") == settings_signature
)
if preview_ready:
    summary = preview_state["summary"]
    st.write(
        f"Rows: {summary['rows_before']:,} -> {summary['rows_after']:,}; "
        f"duplicates to remove: {summary['duplicate_rows_removed']:,}; "
        f"rows to drop for missing values: {summary['rows_dropped_for_missing']:,}."
    )
    if any(summary["conversion_failures"].values()):
        st.write(
            "These non-missing source values would become missing if you apply the "
            "selected conversions. Existing missing values are not counted."
        )
        failure_rows = []
        for column, groups in summary["conversion_failure_details"].items():
            for group in groups:
                examples = []
                for value in group["examples"]:
                    rendered = repr(value)
                    if len(rendered) > 120:
                        rendered = rendered[:117] + "..."
                    examples.append(f"{type(value).__name__}: {rendered}")
                if group["additional_count"]:
                    examples.append(
                        f"{group['additional_count']} more not shown"
                    )
                failure_rows.append(
                    {
                        "Column": conversion_column_labels.get(column, str(column)),
                        "Total failed conversions": summary["conversion_failures"][column],
                        "Failure reason": group["reason"],
                        "Failures of this type": group["count"],
                        "Original examples": "; ".join(examples),
                    }
                )
        st.dataframe(pd.DataFrame(failure_rows), use_container_width=True)
    if summary["missing_values_filled"]:
        st.write("Missing values to fill:")
        st.dataframe(
            pd.DataFrame(
                summary["missing_values_filled"].items(),
                columns=["Column", "Values filled"],
            ),
            use_container_width=True,
        )
    if summary["text_values_changed"]:
        st.write("Text values that would be standardized:")
        st.dataframe(
            pd.DataFrame(
                summary["text_values_changed"].items(),
                columns=["Column", "Values changed"],
            ),
            use_container_width=True,
        )
    st.caption(f"Sample of the proposed result (up to {len(preview_state['sample'])} rows):")
    st.dataframe(preview_state["sample"], use_container_width=True)

if st.button(
    "Apply cleaning",
    key="dq_apply_cleaning",
    disabled=not preview_ready,
):
    try:
        cleaned_df = apply_cleaning(
            current_df,
            settings,
            duplicate_mask=analysis["duplicate_mask"],
            fill_values=preview_state["fill_values"],
        )
        apply_cleaned_dataframe(st.session_state, cleaned_df)
        reset_downstream_widgets()
        st.rerun()
    except Exception as exc:
        st.error(f"Could not apply the cleaning: {exc}")

undo_available = "dq_undo" in st.session_state
if undo_available:
    st.caption(
        "Undo restores the full table that was active before the last Apply. "
        "Edits made after that Apply will also be discarded by Undo."
    )
if st.button("Undo last cleaning", key="dq_undo_cleaning", disabled=not undo_available):
    undo_cleaned_dataframe(st.session_state)
    reset_downstream_widgets()
    st.rerun()
