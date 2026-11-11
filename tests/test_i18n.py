from pathlib import Path

import pandas as pd
import pandas.testing as pdt
import streamlit as st
from streamlit.testing.v1 import AppTest

from components.i18n import EN, RU, LANGUAGE_NAMES, translate


APP_PATH = Path(__file__).resolve().parents[1] / "Data_Explorer.py"
CHARTS_PAGE = "pages/3_Charts.py"
QUALITY_PAGE = "pages/1_Data_Quality.py"
EDITOR_PAGE = "pages/2_Editor.py"
EXPORT_PAGE = "pages/4_Export.py"


def test_new_session_defaults_to_english():
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = pd.DataFrame({"Value": [1, 2]})
    at.session_state["source"] = "language test fixture"

    at.run()

    assert not at.exception
    assert at.session_state["app_language"] == "en"
    assert at.selectbox(key="language_selector_widget").value == "en"
    assert at.title[0].value == "Data Explorer"
    assert LANGUAGE_NAMES == {"en": "English", "ru": "Русский"}


def test_translation_helper_supports_russian_and_falls_back_to_english(monkeypatch):
    assert translate("dq.title") == "Data Quality"
    assert translate("dq.title", "ru") == "Качество данных"

    monkeypatch.setitem(EN, "test.fallback", "English fallback")
    monkeypatch.delitem(RU, "test.fallback", raising=False)
    assert translate("test.fallback", "ru") == "English fallback"
    assert translate("test.missing", "ru") == "test.missing"


def test_language_persists_across_pages_without_resetting_app_state(monkeypatch):
    figures = []
    monkeypatch.setattr(
        st,
        "plotly_chart",
        lambda figure, *args, **kwargs: figures.append(figure),
    )
    dataframe = pd.DataFrame(
        {"Category": ["A", "B", "A"], "Amount": [10, 20, 30]}
    )
    source_dataframe = pd.DataFrame({"Category": ["source"], "Amount": [0]})
    previous_dataframe = pd.DataFrame({"Category": ["old"], "Amount": [5]})
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = source_dataframe.copy(deep=True)
    at.session_state["edited_df"] = dataframe.copy(deep=True)
    at.session_state["source"] = "language workflow fixture"
    at.session_state["data_version"] = 4
    at.session_state["guided_workflow"] = {
        "data_version": 4,
        "completed": ["upload", "validate"],
    }
    at.session_state["dq_undo"] = {
        "had_edited_df": False,
        "previous_df": previous_dataframe.copy(deep=True),
    }
    at.session_state["dq_analysis"] = {"marker": "analysis"}
    at.session_state["dq_preview"] = {"marker": "preview"}
    at.session_state["chart_settings"] = {
        "w_Bar_x": "Category",
        "w_Bar_y": "Amount",
        "w_Bar_agg": "Sum",
        "w_Bar_mode": "Stacked",
    }

    at.run()
    assert not at.exception
    at.session_state["data_version_df_id"] = id(at.session_state["edited_df"])
    assert at.session_state["app_language"] == "en"

    at.switch_page(CHARTS_PAGE).run()
    assert not at.exception
    assert figures
    assert at.selectbox(key="w_Bar_x").value == "Category"
    assert at.selectbox(key="w_Bar_y").value == "Amount"
    assert at.selectbox(key="w_Bar_mode").value == "Stacked"

    progress_before_language_change = dict(at.session_state["guided_workflow"])
    chart_settings_before_language_change = dict(at.session_state["chart_settings"])
    at.switch_page("Data_Explorer.py").run()
    assert not at.exception
    at.selectbox(key="language_selector_widget").set_value("ru").run()

    assert not at.exception
    assert at.session_state["app_language"] == "ru"
    assert at.title[0].value == translate("explorer.title", "ru")
    pdt.assert_frame_equal(at.session_state["df"], source_dataframe)
    pdt.assert_frame_equal(at.session_state["edited_df"], dataframe)
    assert at.session_state["guided_workflow"] == progress_before_language_change
    assert at.session_state["chart_settings"] == chart_settings_before_language_change
    assert at.session_state["dq_undo"]["had_edited_df"] is False
    assert at.session_state["dq_analysis"] == {"marker": "analysis"}
    assert at.session_state["dq_preview"] == {"marker": "preview"}
    pdt.assert_frame_equal(
        at.session_state["dq_undo"]["previous_df"], previous_dataframe
    )

    at.switch_page(CHARTS_PAGE).run()
    assert not at.exception
    assert at.session_state["app_language"] == "ru"
    assert at.title[0].value == translate("charts.title", "ru")
    assert at.selectbox(key="w_Bar_x").value == "Category"
    assert at.selectbox(key="w_Bar_y").value == "Amount"
    assert at.selectbox(key="w_Bar_mode").value == "Stacked"
    assert at.session_state["chart_settings"]["w_Bar_mode"] == "Stacked"


def test_russian_language_is_used_on_quality_and_editor_pages():
    for page, title_key in (
        (QUALITY_PAGE, "dq.title"),
        (EDITOR_PAGE, "editor.title"),
        (EXPORT_PAGE, "export.title"),
    ):
        at = AppTest.from_file(str(APP_PATH))
        at.session_state["df"] = pd.DataFrame({"Value": [1, 2]})
        at.session_state["source"] = "language test fixture"
        at.session_state["app_language"] = "ru"
        at.run()
        assert not at.exception

        at.switch_page(page).run()
        assert not at.exception
        assert at.session_state["app_language"] == "ru"
        assert at.title[0].value == translate(title_key, "ru")
