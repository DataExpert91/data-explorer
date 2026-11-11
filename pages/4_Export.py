"""Prepare downloads and a Data Quality Report from the active dataframe."""

import streamlit as st

from components.exporting import (
    build_quality_report,
    current_missing_policy,
    get_current_export_artifact,
    prepare_csv_export,
    prepare_excel_export,
    profile_report_for_export,
    store_export_artifact,
    validation_result_for_export,
)
from components.i18n import render_language_selector, t
from components.session_data import get_active_dataframe
from components.workflow import (
    mark_workflow_stage_complete,
    render_workflow,
    workflow_stage_available,
)


st.title(t("export.title"))
render_language_selector()
render_workflow("export")

if "df" not in st.session_state:
    st.warning(t("export.no_data"))
    st.stop()

current_df = get_active_dataframe(st.session_state)
data_version = st.session_state.get("data_version", 0)
if not workflow_stage_available(st.session_state, "export"):
    st.info(t("export.no_data"))
    st.stop()

st.caption(t("export.intro"))
get_current_export_artifact(st.session_state, current_df, data_version)
current_validation_result = validation_result_for_export(st.session_state)

if current_validation_result is None:
    st.caption(t("export.validation.not_performed"))
else:
    st.caption(
        t(
            "export.validation.available",
            issues=len(current_validation_result.get("issues", [])),
            warnings=len(current_validation_result.get("warnings", [])),
        )
    )


def mark_export_complete_after_download():
    """Complete Export after the user activates a prepared download."""
    active_df = get_active_dataframe(st.session_state)
    artifact = get_current_export_artifact(
        st.session_state,
        active_df,
        st.session_state.get("data_version", 0),
    )
    if artifact is not None:
        mark_workflow_stage_complete(st.session_state, "export")


def render_export_section(
    *,
    kind,
    title_key,
    description_key,
    prepare_key,
    download_key,
    ready_key,
    error_key,
    filename,
    mime_type,
    prepare_data,
):
    with st.container(border=True):
        st.subheader(t(title_key))
        st.caption(t(description_key))
        if st.button(t(prepare_key), key=f"export_prepare_{kind}"):
            try:
                data = prepare_data()
                store_export_artifact(
                    st.session_state,
                    kind=kind,
                    data=data,
                    filename=filename,
                    mime_type=mime_type,
                    dataframe=current_df,
                    data_version=data_version,
                )
            except Exception as exc:
                st.error(t(error_key, error=exc))

        artifact = get_current_export_artifact(
            st.session_state, current_df, data_version
        )
        if artifact is not None and artifact["kind"] == kind:
            st.success(t(ready_key))
            st.download_button(
                t(download_key),
                data=artifact["data"],
                file_name=artifact["filename"],
                mime=artifact["mime_type"],
                key=f"export_download_{kind}",
                on_click=mark_export_complete_after_download,
            )


render_export_section(
    kind="csv",
    title_key="export.csv.title",
    description_key="export.csv.description",
    prepare_key="export.csv.prepare",
    download_key="export.csv.download",
    ready_key="export.csv.ready",
    error_key="export.csv.error",
    filename="cleaned_data.csv",
    mime_type="text/csv",
    prepare_data=lambda: prepare_csv_export(current_df),
)

render_export_section(
    kind="excel",
    title_key="export.excel.title",
    description_key="export.excel.description",
    prepare_key="export.excel.prepare",
    download_key="export.excel.download",
    ready_key="export.excel.ready",
    error_key="export.excel.error",
    filename="cleaned_data.xlsx",
    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    prepare_data=lambda: prepare_excel_export(current_df),
)


def prepare_report_data():
    treat_blank_strings, missing_tokens = current_missing_policy(st.session_state)
    profile_report = profile_report_for_export(st.session_state, current_df)
    validation_result = current_validation_result
    report = build_quality_report(
        current_df,
        source=st.session_state.get("source"),
        profile_report=profile_report,
        validation_result=validation_result,
        treat_blank_strings=treat_blank_strings,
        missing_tokens=missing_tokens,
        language=st.session_state.get("app_language", "en"),
    )
    return report.encode("utf-8")


render_export_section(
    kind="report",
    title_key="export.report.title_ui",
    description_key="export.report.description",
    prepare_key="export.report.prepare",
    download_key="export.report.download",
    ready_key="export.report.ready",
    error_key="export.report.error",
    filename="data_quality_report.txt",
    mime_type="text/plain; charset=utf-8",
    prepare_data=prepare_report_data,
)
