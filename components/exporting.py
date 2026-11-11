"""On-demand data exports and concise quality report generation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from io import BytesIO

import pandas as pd

from .data_quality import dataframe_signature, profile_dataframe
from .i18n import translate

EXPORT_ARTIFACT_KEY = "export_artifact"


def prepare_csv_export(dataframe: pd.DataFrame) -> bytes:
    """Serialize the provided active dataframe as UTF-8 CSV without its index."""
    return dataframe.to_csv(index=False).encode("utf-8")


def prepare_excel_export(dataframe: pd.DataFrame) -> bytes:
    """Serialize the provided dataframe as an XLSX workbook."""
    buffer = BytesIO()
    dataframe.to_excel(
        buffer,
        index=False,
        sheet_name="Cleaned Data",
        engine="openpyxl",
    )
    return buffer.getvalue()


def current_missing_policy(state) -> tuple[bool, tuple[str, ...]]:
    """Read the existing Data Quality blank-recognition settings."""
    tokens = state.get("dq_missing_tokens", ())
    return (
        bool(state.get("dq_treat_blank_strings", False)),
        tuple(sorted(token.casefold() for token in tokens if isinstance(token, str))),
    )


def profile_report_for_export(state, dataframe: pd.DataFrame) -> dict:
    """Reuse a current Data Quality profile or calculate one for this export."""
    treat_blank_strings, missing_tokens = current_missing_policy(state)
    policy_signature = (treat_blank_strings, missing_tokens)
    version = state.get("data_version", 0)
    expected_signature = (
        dataframe_signature(dataframe, version),
        policy_signature,
    )
    analysis = state.get("dq_analysis")
    if (
        isinstance(analysis, dict)
        and analysis.get("signature") == expected_signature
        and isinstance(analysis.get("report"), dict)
    ):
        return analysis["report"]

    report, _ = profile_dataframe(
        dataframe,
        treat_blank_strings=treat_blank_strings,
        missing_tokens=missing_tokens,
    )
    return report


def validation_result_for_export(state):
    """Return only validation results that match current version and settings."""
    validation = state.get("dq_validation")
    if not isinstance(validation, dict):
        return None
    if validation.get("data_version") != state.get("data_version", 0):
        return None
    if validation.get("missing_policy_signature") != current_missing_policy(state):
        return None
    result = validation.get("result")
    return result if isinstance(result, dict) else None


def _column_label(dataframe: pd.DataFrame, position: int, label_counts: Counter) -> str:
    label = dataframe.columns[position]
    rendered = str(label)
    if not isinstance(label, str) or label_counts[rendered] > 1:
        return f"{label!r} ({type(label).__name__}, column {position + 1})"
    return rendered


def _validation_check_label(check: str, tr) -> str:
    keys = {
        "Dataset size": "validation.check.dataset_size",
        "Missing values": "validation.check.missing",
        "Dataset structure": "validation.check.dataset_structure",
        "Duplicate rows": "validation.check.duplicates",
        "Potential data type mismatch": "validation.check.type_mismatch",
        "Missing value check": "validation.check.missing_assessment",
        "Data type check": "validation.check.type",
    }
    key = keys.get(check)
    return tr(key) if key else check


def _validation_issue_message(issue: dict, result: dict, tr) -> str:
    check = issue.get("check")
    if check == "Dataset size":
        return tr("validation.issue.no_rows")
    if check == "Dataset structure":
        return tr("validation.issue.no_columns")
    if check == "Missing values":
        return tr(
            "validation.issue.missing",
            count=issue.get("count", 0),
            columns=len(result.get("columns_with_missing", [])),
        )
    if check == "Duplicate rows" and issue.get("count") is not None:
        return tr("validation.issue.duplicates", count=issue["count"])

    message = issue.get("message", "")
    duplicate_prefix = "Duplicate detection could not be completed:"
    if message.startswith(duplicate_prefix):
        return tr(
            "dq.duplicate_detection_error",
            detail=message[len(duplicate_prefix):].strip(),
        )
    return message


def _validation_warning_message(message: str, tr) -> str:
    keys = {
        "The dataset contains no rows.": "validation.warning.no_rows",
        "Missing values could not be assessed because the dataset has no rows.":
            "validation.warning.no_rows",
        "Data types could not be assessed because the dataset has no columns.":
            "validation.warning.no_columns",
        "Mixed values may indicate inconsistent types": "validation.warning.type_mixed",
        "Mostly numeric-looking text": "validation.warning.type_numeric",
        "Mostly date-looking text": "validation.warning.type_date",
    }
    key = keys.get(message)
    return tr(key) if key else message


def build_quality_report(
    dataframe: pd.DataFrame,
    *,
    source: str | None = None,
    profile_report: dict | None = None,
    validation_result: dict | None = None,
    treat_blank_strings: bool = False,
    missing_tokens=(),
    language: str = "en",
    generated_at: datetime | None = None,
) -> str:
    """Build a read-only text report using the existing profile/validation data."""
    tr = lambda key, **values: translate(key, language, **values)
    if profile_report is None:
        profile_report, _ = profile_dataframe(
            dataframe,
            treat_blank_strings=treat_blank_strings,
            missing_tokens=missing_tokens,
        )

    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    elif generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    timestamp = generated_at.isoformat(timespec="seconds")
    source_name = source.strip() if isinstance(source, str) else ""
    if not source_name:
        source_name = tr("export.report.dataset_unknown")

    lines = [
        tr("export.report.title"),
        "",
        f"{tr('export.report.generated_at')}: {timestamp}",
        f"{tr('export.report.dataset')}: {source_name}",
        "",
        tr("export.report.overview"),
        f"{tr('export.report.rows')}: {profile_report['rows']:,}",
        f"{tr('export.report.columns')}: {profile_report['columns']:,}",
        "",
        tr("export.report.column_names"),
    ]

    label_counts = Counter(str(label) for label in dataframe.columns)
    for position in range(len(dataframe.columns)):
        lines.append(f"{position + 1}. {_column_label(dataframe, position, label_counts)}")

    actual_missing = int(profile_report.get("actual_missing", 0))
    recognized_missing = int(profile_report.get("recognized_as_missing", 0))
    lines.extend(
        [
            "",
            tr("export.report.missing_values"),
            f"{tr('export.report.total_missing')}: {profile_report['total_missing']:,}",
            f"{tr('export.report.actual_missing')}: {actual_missing:,}",
            f"{tr('export.report.recognized_missing')}: {recognized_missing:,}",
        ]
    )
    missing_columns = [
        (position, item)
        for position, item in enumerate(profile_report["column_report"])
        if item["Missing"]
    ]
    if missing_columns:
        for position, item in missing_columns:
            label = _column_label(dataframe, position, label_counts)
            lines.append(
                f"- {label}: {item['Missing']:,} ({item['Missing %']:.1f}%)"
            )
    else:
        lines.append(tr("export.report.no_missing"))

    duplicate_rows = profile_report.get("duplicate_rows")
    lines.extend(["", tr("export.report.duplicate_rows")])
    if duplicate_rows is None:
        lines.append(tr("common.unavailable"))
        if profile_report.get("duplicate_error"):
            message = profile_report["duplicate_error"]
            duplicate_prefix = "Duplicate detection could not be completed:"
            if message.startswith(duplicate_prefix):
                message = tr(
                    "dq.duplicate_detection_error",
                    detail=message[len(duplicate_prefix):].strip(),
                )
            lines.append(message)
    else:
        lines.append(f"{duplicate_rows:,}")

    lines.extend(["", tr("export.report.data_types")])
    for position, item in enumerate(profile_report["column_report"]):
        label = _column_label(dataframe, position, label_counts)
        lines.append(f"- {label}: {item['Data type']}")

    lines.extend(["", tr("export.report.validation")])
    if validation_result is None:
        lines.append(tr("export.report.validation_not_performed"))
    else:
        lines.append(
            tr(
                "validation.completed",
                issues=len(validation_result.get("issues", [])),
                warnings=len(validation_result.get("warnings", [])),
                passed=len(validation_result.get("passed_checks", [])),
            )
        )
        for section_key, result_key in (
            ("export.report.validation_issues", "issues"),
            ("export.report.validation_warnings", "warnings"),
            ("export.report.validation_passed", "passed_checks"),
        ):
            items = validation_result.get(result_key, [])
            lines.append(tr(section_key))
            if not items:
                lines.append(f"- {tr('export.report.no_findings')}")
                continue
            for item in items:
                if result_key == "passed_checks":
                    passed_keys = {
                        "No missing values detected.": "validation.pass.no_missing",
                        "No duplicate rows detected.": "validation.pass.no_duplicates",
                        "No obvious data type inconsistencies detected.":
                            "validation.pass.no_type_mismatch",
                    }
                    key = passed_keys.get(item)
                    text = tr(key) if key else item
                elif result_key == "issues":
                    text = (
                        f"{_validation_check_label(item.get('check', ''), tr)}: "
                        f"{_validation_issue_message(item, validation_result, tr)}"
                    )
                else:
                    details = []
                    if item.get("column"):
                        details.append(
                            f"{tr('common.column')}: {item['column']}"
                        )
                    if item.get("suggested_type"):
                        type_keys = {
                            "Text": "dq.type.Text",
                            "Integer": "dq.type.Integer",
                            "Number": "dq.type.Number",
                            "Date/Time": "dq.type.Date/Time",
                        }
                        suggested_type = item["suggested_type"]
                        type_key = type_keys.get(suggested_type)
                        if type_key:
                            suggested_type = tr(type_key)
                        details.append(
                            f"{tr('common.suggested_type')}: {suggested_type}"
                        )
                    details_text = f" ({'; '.join(details)})" if details else ""
                    text = (
                        f"{_validation_check_label(item.get('check', ''), tr)}: "
                        f"{_validation_warning_message(item.get('message', ''), tr)}"
                        f"{details_text}"
                    )
                lines.append(f"- {text}")

    lines.extend(
        [
            "",
            tr("export.report.cleaning_history"),
            tr("export.report.cleaning_history_unavailable"),
        ]
    )
    return "\n".join(lines) + "\n"


def store_export_artifact(
    state,
    *,
    kind: str,
    data: bytes,
    filename: str,
    mime_type: str,
    dataframe: pd.DataFrame,
    data_version: int,
) -> None:
    """Keep one prepared download in session state, tied to the active version."""
    state[EXPORT_ARTIFACT_KEY] = {
        "kind": kind,
        "data": data,
        "filename": filename,
        "mime_type": mime_type,
        "data_version": data_version,
        "dataframe_id": id(dataframe),
    }


def get_current_export_artifact(state, dataframe: pd.DataFrame, data_version: int):
    """Return the prepared artifact only while its active dataframe is unchanged."""
    artifact = state.get(EXPORT_ARTIFACT_KEY)
    if not isinstance(artifact, dict):
        return None
    if (
        artifact.get("data_version") != data_version
        or artifact.get("dataframe_id") != id(dataframe)
    ):
        state.pop(EXPORT_ARTIFACT_KEY, None)
        return None
    return artifact
