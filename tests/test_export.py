from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
import pandas.testing as pdt
import streamlit as st
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

import components.exporting as exporting
from components.data_quality import profile_dataframe, validate_dataframe
from components.exporting import (
    build_quality_report,
    get_current_export_artifact,
    prepare_csv_export,
    prepare_excel_export,
    store_export_artifact,
)


APP_PATH = Path(__file__).resolve().parents[1] / "Data_Explorer.py"
EXPORT_PAGE = "pages/4_Export.py"


def _open_export(source_df, active_df=None):
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = source_df.copy(deep=True)
    at.session_state["source"] = "export test.csv"
    if active_df is not None:
        at.session_state["edited_df"] = active_df.copy(deep=True)
    at.session_state["data_version"] = 7
    at.run()
    assert not at.exception
    at.session_state["data_version_df_id"] = id(
        at.session_state.get("edited_df", at.session_state["df"])
    )
    at.switch_page(EXPORT_PAGE).run()
    assert not at.exception
    return at


def test_csv_export_is_utf8_and_preserves_headers_and_values():
    dataframe = pd.DataFrame(
        {"Категория": ["чай", "кофе"], "Amount": [2, 5]}
    )
    original = dataframe.copy(deep=True)

    csv_bytes = prepare_csv_export(dataframe)
    restored = pd.read_csv(StringIO(csv_bytes.decode("utf-8")))

    pdt.assert_frame_equal(restored, dataframe)
    pdt.assert_frame_equal(dataframe, original)


def test_excel_export_uses_cleaned_data_sheet_and_preserves_headers_and_values():
    dataframe = pd.DataFrame({"Category": ["A", "B"], "Amount": [3, 8]})
    original = dataframe.copy(deep=True)

    workbook = load_workbook(BytesIO(prepare_excel_export(dataframe)), data_only=True)

    assert workbook.sheetnames == ["Cleaned Data"]
    worksheet = workbook["Cleaned Data"]
    assert list(worksheet.values) == [
        ("Category", "Amount"),
        ("A", 3),
        ("B", 8),
    ]
    pdt.assert_frame_equal(dataframe, original)


def test_quality_report_includes_profile_and_unperformed_history_states():
    dataframe = pd.DataFrame(
        {
            "name": ["", " N/A ", None, "x", "x"],
            "value": [1, 2, 3, 1, 1],
        }
    )
    profile, _ = profile_dataframe(
        dataframe,
        treat_blank_strings=True,
        missing_tokens=["N/A"],
    )
    generated_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    report = build_quality_report(
        dataframe,
        source="sample.csv",
        profile_report=profile,
        treat_blank_strings=True,
        missing_tokens=["N/A"],
        generated_at=generated_at,
    )

    assert "Generated at (UTC): 2026-01-02T03:04:05+00:00" in report
    assert "Dataset: sample.csv" in report
    assert "Rows: 5" in report
    assert "Columns: 2" in report
    assert "Column names" in report
    assert "name" in report and "value" in report
    assert "Total missing values: 3" in report
    assert "Actual pandas nulls: 1" in report
    assert "Additional blank-like values recognized: 2" in report
    assert "Duplicate rows\n1" in report
    assert "Data types by column" in report
    assert "Validation has not been performed" in report
    assert "Operation history is not tracked" in report


def test_quality_report_uses_existing_validation_result_and_findings():
    dataframe = pd.DataFrame({"value": [1, None, 3]})
    profile, _ = profile_dataframe(dataframe)
    validation = validate_dataframe(dataframe, profile_report=profile)

    report = build_quality_report(
        dataframe,
        profile_report=profile,
        validation_result=validation,
        language="ru",
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert "Последний результат проверки" in report
    assert "Проверка завершена" in report
    assert "Пропущенные значения" in report
    assert "Осталось пропусков: 1" in report


def test_report_disambiguates_mixed_type_column_labels():
    dataframe = pd.DataFrame([[10, 20]], columns=[1, "1"])
    profile, _ = profile_dataframe(dataframe)

    report = build_quality_report(dataframe, profile_report=profile)

    assert "1 (int, column 1)" in report
    assert "'1' (str, column 2)" in report


def test_export_page_uses_active_dataframe_and_marks_completion_on_download():
    source_df = pd.DataFrame({"Category": ["source"], "Amount": [1]})
    active_df = pd.DataFrame({"Category": ["cleaned"], "Amount": [9]})
    at = _open_export(source_df, active_df)
    original_chart_settings = {"w_Bar_mode": "Stacked"}
    at.session_state["chart_settings"] = dict(original_chart_settings)
    at.run()
    assert not at.exception
    at.switch_page(EXPORT_PAGE).run()
    assert not at.exception

    assert "export" not in at.session_state["guided_workflow"]["completed"]
    at.button(key="export_prepare_csv").click().run()

    assert not at.exception
    artifact = at.session_state["export_artifact"]
    assert artifact["kind"] == "csv"
    assert artifact["data"] == prepare_csv_export(active_df)
    assert at.download_button(key="export_download_csv")
    assert "export" not in at.session_state["guided_workflow"]["completed"]
    pdt.assert_frame_equal(at.session_state["df"], source_df)
    pdt.assert_frame_equal(at.session_state["edited_df"], active_df)
    assert at.session_state["chart_settings"] == original_chart_settings

    at.download_button(key="export_download_csv").click().run()

    assert not at.exception
    assert "export" in at.session_state["guided_workflow"]["completed"]
    pdt.assert_frame_equal(at.session_state["df"], source_df)
    pdt.assert_frame_equal(at.session_state["edited_df"], active_df)
    assert at.session_state["chart_settings"] == original_chart_settings


def test_export_preparation_failure_does_not_complete_workflow(monkeypatch):
    at = _open_export(pd.DataFrame({"value": [1, 2]}))

    def fail_export(_dataframe):
        raise OSError("simulated export failure")

    monkeypatch.setattr(exporting, "prepare_csv_export", fail_export)
    at.button(key="export_prepare_csv").click().run()

    assert not at.exception
    assert "export" not in at.session_state["guided_workflow"]["completed"]
    assert "export_artifact" not in at.session_state
    assert any("Could not prepare the CSV file" in item.value for item in at.error)


def test_prepared_artifact_is_invalidated_after_active_dataframe_replacement():
    state = {"data_version": 1}
    first = pd.DataFrame({"value": [1]})
    second = pd.DataFrame({"value": [2]})
    store_export_artifact(
        state,
        kind="csv",
        data=prepare_csv_export(first),
        filename="cleaned_data.csv",
        mime_type="text/csv",
        dataframe=first,
        data_version=1,
    )

    assert get_current_export_artifact(state, first, 1) is not None
    assert get_current_export_artifact(state, second, 2) is None
    assert "export_artifact" not in state


def test_export_page_localizes_russian_controls():
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = pd.DataFrame({"value": [1]})
    at.session_state["source"] = "export test.csv"
    at.session_state["app_language"] = "ru"
    at.run()
    assert not at.exception

    at.switch_page(EXPORT_PAGE).run()

    assert not at.exception
    assert at.title[0].value == "Экспорт и отчёты"
    assert any(button.label == "Подготовить CSV к скачиванию" for button in at.button)
    assert any(button.label == "Подготовить отчёт к скачиванию" for button in at.button)


def test_export_page_uses_english_by_default():
    at = _open_export(pd.DataFrame({"value": [1]}))

    assert at.session_state["app_language"] == "en"
    assert at.title[0].value == "Export & Reports"
    assert any(button.label == "Prepare CSV download" for button in at.button)


def test_export_page_has_no_download_actions_without_a_dataset():
    at = AppTest.from_file(str(APP_PATH))
    at.run()
    assert not at.exception
    assert "df" not in at.session_state
    at.switch_page(EXPORT_PAGE)
    at.run()

    assert not at.exception
    assert any("No data loaded" in warning.value for warning in at.warning)
    assert not any(button.key.startswith("export_prepare_") for button in at.button)
