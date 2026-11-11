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
    validate_dataframe,
)
from components.i18n import render_language_selector, t
from components.session_data import (
    apply_cleaned_dataframe,
    ensure_data_version,
    get_active_dataframe,
    undo_cleaned_dataframe,
)
from components.workflow import (
    clear_workflow_stage,
    mark_workflow_stage_complete,
    render_workflow,
)

DQ_PREVIEW_FORMAT_VERSION = 3


st.title(t("dq.title"))
render_language_selector()
st.caption(t("dq.intro"))

if "df" not in st.session_state:
    st.warning(t("dq.no_data"))
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
st.caption(t("dq.current_dataset", source=source_name))
st.caption(
    t(
        "dq.profiling_size",
        rows=len(current_df),
        columns=len(current_df.columns),
    )
)
if has_duplicate_labels:
    st.warning(t("dq.duplicate_columns_warning"))

with st.expander(t("dq.blank_recognition"), expanded=False):
    treat_blank_strings = st.checkbox(
        t("dq.blank_strings"),
        key="dq_treat_blank_strings",
        help=t("dq.blank_strings_help"),
    )
    missing_tokens = st.multiselect(
        t("dq.missing_tokens"),
        options=COMMON_MISSING_TEXT_TOKENS,
        key="dq_missing_tokens",
        help=t("dq.missing_tokens_help"),
    )

missing_policy_signature = (
    bool(treat_blank_strings),
    tuple(sorted(token.casefold() for token in missing_tokens)),
)
analysis_signature = (current_signature, missing_policy_signature)

analysis = st.session_state.get("dq_analysis")
if analysis is not None and analysis.get("signature") != analysis_signature:
    invalidate_quality_results()
    clear_workflow_stage(st.session_state, "profile")
    analysis = None

if analysis is not None:
    mark_workflow_stage_complete(st.session_state, "profile")

validation_state = st.session_state.get("dq_validation")
if validation_state is not None and (
    validation_state.get("data_version") != st.session_state["data_version"]
    or validation_state.get("missing_policy_signature") != missing_policy_signature
):
    st.session_state.pop("dq_validation", None)
    clear_workflow_stage(st.session_state, "validate")
    validation_state = None
elif validation_state is not None:
    mark_workflow_stage_complete(st.session_state, "validate")

render_workflow("quality")

column_label_counts = Counter(str(column) for column in current_df.columns)
conversion_column_labels = {}
for position, column in enumerate(current_df.columns):
    label = str(column)
    if column_label_counts[label] > 1 or not isinstance(column, str):
        label = f"{label} ({type(column).__name__}, column {position + 1})"
    conversion_column_labels[column] = label

st.subheader(t("dq.quality_analysis"))
if st.button(t("dq.run_analysis"), key="dq_run_analysis"):
    with st.spinner(t("dq.analysis_spinner")):
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
            mark_workflow_stage_complete(st.session_state, "profile")
            st.session_state.pop("dq_preview", None)
            st.rerun()
        except Exception as exc:
            st.error(t("dq.analysis_error", error=exc))

analysis = st.session_state.get("dq_analysis")
if analysis is None or analysis.get("signature") != analysis_signature:
    st.info(t("dq.analysis_required"))
else:
    report = analysis["report"]
    metrics = st.columns(4)
    metrics[0].metric(t("common.rows"), f"{report['rows']:,}")
    metrics[1].metric(t("common.columns"), f"{report['columns']:,}")
    complete_percent = report["complete_percent"]
    metrics[2].metric(
        t("dq.complete_cells"),
        t("common.not_applicable")
        if complete_percent is None
        else f"{complete_percent:.1f}%",
    )
    if report["duplicate_rows"] is None:
        metrics[3].metric(t("dq.duplicate_rows"), t("common.unavailable"))
    else:
        metrics[3].metric(t("dq.duplicate_rows"), f"{report['duplicate_rows']:,}")

    if report["duplicate_error"]:
        duplicate_error = report["duplicate_error"]
        prefix = "Duplicate detection could not be completed:"
        if duplicate_error.startswith(prefix):
            duplicate_error = t(
                "dq.duplicate_detection_error",
                detail=duplicate_error[len(prefix):].strip(),
            )
        st.warning(duplicate_error)

    column_report = pd.DataFrame(report["column_report"])
    column_headers = {
        "Position": t("common.position"),
        "Column": t("common.column"),
        "Data type": t("common.data_type"),
        "Non-missing": t("common.non_missing"),
        "Missing": t("common.missing"),
        "Actual missing": t("common.actual_missing"),
        "Recognized as missing": t("common.recognized_missing"),
        "Missing %": t("common.missing_percent"),
        "Complete %": t("common.complete_percent"),
        "Potential mismatch": t("common.potential_mismatch"),
        "Suggested type": t("common.suggested_type"),
    }
    column_report = column_report.rename(columns=column_headers)
    mismatch_header = t("common.potential_mismatch")
    suggested_header = t("common.suggested_type")
    mismatch_translations = {
        "Mostly numeric-looking text": t("dq.mismatch.numeric_text"),
        "Mostly date-looking text": t("dq.mismatch.date_text"),
        "Mixed values may indicate inconsistent types": t("dq.mismatch.mixed"),
    }
    column_report[mismatch_header] = column_report[mismatch_header].replace(
        mismatch_translations
    )
    type_translations = {
        "Text": t("dq.type.Text"),
        "Integer": t("dq.type.Integer"),
        "Number": t("dq.type.Number"),
        "Date/Time": t("dq.type.Date/Time"),
    }
    column_report[suggested_header] = column_report[suggested_header].replace(
        type_translations
    )
    st.dataframe(column_report, use_container_width=True)

    date_candidates = [
        f"{row['Column']} (column {row['Position']})" if has_duplicate_labels else row["Column"]
        for row in report["column_report"]
        if row["Suggested type"] == "Date/Time"
    ]
    if date_candidates:
        st.caption(t("dq.date_text_caption", columns=", ".join(date_candidates)))
    mismatch_candidates = [
        row for row in report["column_report"] if row["Potential mismatch"]
    ]
    if mismatch_candidates:
        st.caption(
            t("dq.type_mismatch_caption", count=len(mismatch_candidates))
        )

st.subheader(t("dq.cleaning_preview"))
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
    t("dq.columns_to_convert"),
    options=cleaning_columns,
    key="dq_convert_columns",
    disabled=has_duplicate_labels,
    help=t("dq.columns_to_convert_help"),
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
        t("dq.target_type_for", column=column),
        options=target_types,
        index=target_types.index(previous_target),
        key=widget_key,
        format_func=lambda value: t(f"dq.type.{value}"),
    )

date_format = None
if any(target == "Date/Time" for target in conversions.values()):
    date_format = st.text_input(
        t("dq.date_format"),
        placeholder=t("dq.date_format_placeholder"),
        key="dq_date_format",
        help=t("dq.date_format_help"),
    ).strip() or None

remove_duplicates = st.checkbox(
    t("dq.remove_duplicates"),
    key="dq_remove_duplicates",
    help=t("dq.remove_duplicates_help"),
)

missing_actions = ["Leave unchanged", "Drop rows", "Fill values"]
if st.session_state.get("dq_missing_action") not in missing_actions:
    st.session_state["dq_missing_action"] = "Leave unchanged"
missing_action = st.selectbox(
    t("dq.missing_action"),
    options=missing_actions,
    key="dq_missing_action",
    format_func=lambda value: t(f"dq.missing_action.{value}"),
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
        t("dq.drop_rows_columns"),
        options=cleaning_columns,
        key="dq_drop_missing_columns",
        disabled=has_duplicate_labels,
        help=t("dq.drop_rows_help"),
    )
elif missing_action == "Fill values":
    fill_strategies = [
        "Constant",
        "Mean",
        "Median",
        "Mode",
        "Forward Fill",
        "Backward Fill",
    ]
    if st.session_state.get("dq_fill_strategy") not in fill_strategies:
        st.session_state["dq_fill_strategy"] = "Mode"
    fill_strategy = st.selectbox(
        t("dq.fill_strategy"),
        options=fill_strategies,
        key="dq_fill_strategy",
        format_func=lambda value: t(f"dq.fill.{value}"),
    )
    fill_options = numeric_columns if fill_strategy in {"Mean", "Median"} else columns
    keep_valid_selection("dq_fill_columns", set(fill_options))
    fill_columns = st.multiselect(
        t("dq.fill_columns"),
        options=fill_options,
        key="dq_fill_columns",
        disabled=has_duplicate_labels,
    )
    if fill_strategy == "Constant":
        fill_constant = st.text_input(
            t("dq.fill_constant"), key="dq_fill_constant"
        )

st.subheader(t("dq.drop_threshold_title"))
threshold_control_disabled = len(current_df) == 0 or len(columns) == 0
if len(current_df) == 0:
    st.info(t("dq.zero_rows_threshold"))
elif len(columns) == 0:
    st.info(t("dq.no_columns_threshold"))
threshold_enabled = st.checkbox(
    t("dq.threshold_enabled"),
    key="dq_enable_column_threshold",
    disabled=threshold_control_disabled,
)
drop_columns_threshold = None
if threshold_enabled and not threshold_control_disabled:
    drop_columns_threshold = st.slider(
        t("dq.threshold_label"),
        min_value=0,
        max_value=100,
        value=50,
        step=1,
        format="%d%%",
        key="dq_missing_column_threshold",
        help=t("dq.threshold_help"),
    )

keep_valid_selection("dq_standardize_columns", set(text_columns))
standardize_columns = st.multiselect(
    t("dq.standardize_columns"),
    options=text_columns,
    key="dq_standardize_columns",
    disabled=has_duplicate_labels,
)
text_actions = {"enabled": bool(standardize_columns)}
if standardize_columns:
    text_actions["trim"] = st.checkbox(t("dq.trim"), key="dq_trim")
    text_actions["collapse_whitespace"] = st.checkbox(
        t("dq.collapse_whitespace"), key="dq_collapse_whitespace"
    )
    case_options = ["Preserve case", "lowercase", "Title Case"]
    if st.session_state.get("dq_case") not in case_options:
        st.session_state["dq_case"] = "Preserve case"
    text_actions["case"] = st.selectbox(
        t("dq.case"),
        options=case_options,
        key="dq_case",
        format_func=lambda value: t(f"dq.case.{value}"),
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
    "drop_columns_threshold": drop_columns_threshold,
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
    or drop_columns_threshold is not None
    or standardize_columns
)
analysis_ready = analysis is not None and analysis.get("signature") == analysis_signature
if st.button(
    t("dq.preview_button"),
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
        st.error(t("dq.preview_error", error=exc))

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
        t(
            "dq.preview_rows",
            before=summary["rows_before"],
            after=summary["rows_after"],
            duplicates=summary["duplicate_rows_removed"],
            missing_rows=summary["rows_dropped_for_missing"],
        )
    )
    if any(summary["conversion_failures"].values()):
        st.write(t("dq.conversion_failure_intro"))
        failure_rows = []
        failure_reason_keys = {
            "Not a valid number": "dq.failure.not_number",
            "Not numeric": "dq.failure.not_numeric",
            "Fractional numeric value (not a whole number)": "dq.failure.fractional",
            "Non-finite numeric value": "dq.failure.non_finite",
            "Could not parse as Date/Time": "dq.failure.date",
        }
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
                        t("dq.more_examples", count=group["additional_count"])
                    )
                failure_rows.append(
                    {
                        t("common.column"): conversion_column_labels.get(column, str(column)),
                        t("dq.failure_total"): summary["conversion_failures"][column],
                        t("dq.failure_reason"): t(
                            failure_reason_keys.get(group["reason"], group["reason"])
                        ),
                        t("common.failed_count"): group["count"],
                        t("dq.original_examples"): "; ".join(examples),
                    }
                )
        st.dataframe(pd.DataFrame(failure_rows), use_container_width=True)
    if summary["missing_values_filled"]:
        st.write(t("dq.fill_results"))
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        t("common.column"): column,
                        t("dq.values_filled"): count,
                        t("dq.missing_remaining"): summary["missing_values_remaining"].get(column, 0),
                    }
                    for column, count in summary["missing_values_filled"].items()
                ]
            ),
            use_container_width=True,
        )
    if summary["column_drop_threshold"] is not None:
        st.write(
            t(
                "dq.columns_at_threshold",
                threshold=summary["column_drop_threshold"],
            )
        )
        if summary["columns_to_drop"]:
            drop_columns_table = pd.DataFrame(summary["columns_to_drop"])
            drop_columns_table = drop_columns_table.rename(
                columns={
                    "Position": t("common.position"),
                    "Column": t("common.column"),
                    "Label type": t("common.label_type"),
                    "Missing %": t("common.missing_percent"),
                }
            )
            st.dataframe(
                drop_columns_table,
                use_container_width=True,
            )
        else:
            st.caption(t("dq.no_columns_meet_threshold"))
        st.write(t("dq.columns_remaining", count=summary["columns_remaining"]))
    if summary["text_values_changed"]:
        st.write(t("dq.standardized_text"))
        st.dataframe(
            pd.DataFrame(
                summary["text_values_changed"].items(),
                columns=[t("common.column"), t("dq.values_changed")],
            ),
            use_container_width=True,
        )
    st.caption(
        t("dq.preview_sample", count=len(preview_state["sample"]))
    )
    st.dataframe(preview_state["sample"], use_container_width=True)

if st.button(
    t("dq.apply"),
    key="dq_apply_cleaning",
    disabled=not preview_ready,
):
    try:
        cleaned_df = apply_cleaning(
            current_df,
            settings,
            duplicate_mask=analysis["duplicate_mask"],
            fill_values=preview_state["fill_values"],
            drop_column_positions=[
                row["Position"] - 1 for row in preview_state["summary"]["columns_to_drop"]
            ],
        )
        apply_cleaned_dataframe(st.session_state, cleaned_df)
        mark_workflow_stage_complete(st.session_state, "clean")
        reset_downstream_widgets()
        st.rerun()
    except Exception as exc:
        st.error(t("dq.apply_error", error=exc))

undo_available = "dq_undo" in st.session_state
if undo_available:
    st.caption(t("dq.undo_caption"))
if st.button(t("dq.undo"), key="dq_undo_cleaning", disabled=not undo_available):
    undo_cleaned_dataframe(st.session_state)
    reset_downstream_widgets()
    st.rerun()

st.subheader(t("validation.title"))
st.caption(t("validation.intro"))
if st.button(t("validation.run"), key="dq_run_validation"):
    try:
        current_analysis = st.session_state.get("dq_analysis")
        if (
            current_analysis is not None
            and current_analysis.get("signature") == analysis_signature
        ):
            profile_report = current_analysis["report"]
        else:
            profile_report, _ = profile_dataframe(
                current_df,
                treat_blank_strings=treat_blank_strings,
                missing_tokens=missing_tokens,
            )
        result = validate_dataframe(
            current_df,
            treat_blank_strings=treat_blank_strings,
            missing_tokens=missing_tokens,
            profile_report=profile_report,
        )
        st.session_state["dq_validation"] = {
            "data_version": st.session_state["data_version"],
            "missing_policy_signature": missing_policy_signature,
            "result": result,
        }
        mark_workflow_stage_complete(st.session_state, "validate")
        st.rerun()
    except Exception as exc:
        st.error(t("validation.error", error=exc))

validation_state = st.session_state.get("dq_validation")
if validation_state is not None:
    result = validation_state["result"]
    st.success(
        t(
            "validation.completed",
            issues=len(result["issues"]),
            warnings=len(result["warnings"]),
            passed=len(result["passed_checks"]),
        )
    )
    metrics = st.columns(5)
    metrics[0].metric(t("common.rows"), f"{result['rows']:,}")
    metrics[1].metric(t("common.columns"), f"{result['columns']:,}")
    metrics[2].metric(t("validation.missing_values"), f"{result['total_missing']:,}")
    metrics[3].metric(
        t("dq.duplicate_rows"),
        t("common.unavailable")
        if result["duplicate_rows"] is None
        else f"{result['duplicate_rows']:,}",
    )
    metrics[4].metric(
        t("validation.items_attention"),
        f"{result['remaining_issue_count']:,}",
    )

    with st.expander(t("validation.details"), expanded=False):
        st.markdown(f"**{t('validation.passed')}**")
        if result["passed_checks"]:
            passed_translations = {
                "No missing values detected.": t("validation.pass.no_missing"),
                "No duplicate rows detected.": t("validation.pass.no_duplicates"),
                "No obvious data type inconsistencies detected.": t(
                    "validation.pass.no_type_mismatch"
                ),
            }
            st.markdown(
                "\n".join(
                    f"- {passed_translations.get(check, check)}"
                    for check in result["passed_checks"]
                )
            )
        else:
            st.caption(t("validation.no_passed"))

        if result["issues"]:
            st.markdown(f"**{t('validation.issues')}**")
            check_labels = {
                "Dataset size": t("validation.check.dataset_size"),
                "Missing values": t("validation.check.missing"),
                "Dataset structure": t("validation.check.dataset_structure"),
                "Duplicate rows": t("validation.check.duplicates"),
            }
            issue_messages = []
            for issue in result["issues"]:
                check = issue["check"]
                if check == "Dataset size":
                    message = t("validation.issue.no_rows")
                elif check == "Dataset structure":
                    message = t("validation.issue.no_columns")
                elif check == "Missing values":
                    message = t(
                        "validation.issue.missing",
                        count=issue["count"],
                        columns=len(result["columns_with_missing"]),
                    )
                elif check == "Duplicate rows" and issue["count"] is not None:
                    message = t(
                        "validation.issue.duplicates", count=issue["count"]
                    )
                else:
                    message = issue["message"]
                    duplicate_prefix = "Duplicate detection could not be completed:"
                    if message.startswith(duplicate_prefix):
                        message = t(
                            "dq.duplicate_detection_error",
                            detail=message[len(duplicate_prefix):].strip(),
                        )
                issue_messages.append(
                    {
                        t("validation.check_header"): check_labels.get(check, check),
                        t("validation.message_header"): message,
                        t("validation.count_header"): issue["count"],
                    }
                )
            st.dataframe(pd.DataFrame(issue_messages), use_container_width=True)
        if result["warnings"]:
            st.markdown(f"**{t('validation.warnings')}**")
            warning_rows = []
            warning_checks = {
                "Potential data type mismatch": t("validation.check.type_mismatch"),
                "Missing value check": t("validation.check.missing_assessment"),
                "Data type check": t("validation.check.type"),
            }
            warning_messages = {
                "The dataset contains no rows.": t("validation.warning.no_rows"),
                "Data types could not be assessed because the dataset has no columns.": t(
                    "validation.warning.no_columns"
                ),
                "Mixed values may indicate inconsistent types": t(
                    "validation.warning.type_mixed"
                ),
                "Mostly numeric-looking text": t("validation.warning.type_numeric"),
                "Mostly date-looking text": t("validation.warning.type_date"),
            }
            for warning in result["warnings"]:
                warning_rows.append(
                    {
                        t("validation.check_header"): warning_checks.get(
                            warning["check"], warning["check"]
                        ),
                        t("common.position"): warning.get("position"),
                        t("common.column"): warning.get("column", ""),
                        t("validation.message_header"): warning_messages.get(
                            warning.get("message"), warning.get("message", "")
                        ),
                        t("common.suggested_type"): {
                            "Number": t("dq.type.Number"),
                            "Date/Time": t("dq.type.Date/Time"),
                        }.get(warning.get("suggested_type"), ""),
                    }
                )
            st.dataframe(pd.DataFrame(warning_rows), use_container_width=True)
        if result["columns_with_missing"]:
            st.markdown(f"**{t('validation.columns_missing')}**")
            missing_columns_table = pd.DataFrame(result["columns_with_missing"])
            missing_columns_table = missing_columns_table.rename(
                columns={
                    "Position": t("common.position"),
                    "Column": t("common.column"),
                    "Missing": t("common.missing"),
                    "Missing %": t("common.missing_percent"),
                }
            )
            st.dataframe(
                missing_columns_table,
                use_container_width=True,
            )
        st.markdown(f"**{t('validation.column_types')}**")
        column_types_table = pd.DataFrame(result["column_types"])
        column_types_table = column_types_table.rename(
            columns={
                "Position": t("common.position"),
                "Column": t("common.column"),
                "Data type": t("common.data_type"),
                "Potential mismatch": t("common.potential_mismatch"),
                "Suggested type": t("common.suggested_type"),
            }
        )
        mismatch_header = t("common.potential_mismatch")
        column_types_table[mismatch_header] = column_types_table[mismatch_header].replace(
            {
                "Mixed values may indicate inconsistent types": t("dq.mismatch.mixed"),
                "Mostly numeric-looking text": t("dq.mismatch.numeric_text"),
                "Mostly date-looking text": t("dq.mismatch.date_text"),
            }
        )
        suggested_header = t("common.suggested_type")
        validation_type_translations = {
            "Text": t("dq.type.Text"),
            "Integer": t("dq.type.Integer"),
            "Number": t("dq.type.Number"),
            "Date/Time": t("dq.type.Date/Time"),
        }
        column_types_table[suggested_header] = column_types_table[suggested_header].replace(
            validation_type_translations
        )
        st.dataframe(column_types_table, use_container_width=True)
