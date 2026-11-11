from pathlib import Path

import pandas as pd
import pandas.testing as pdt
from streamlit.testing.v1 import AppTest

from components.session_data import bump_data_version
from components.workflow import (
    COMPLETED,
    IN_PROGRESS,
    NOT_STARTED,
    WORKFLOW_STAGES,
    mark_workflow_stage_complete,
    workflow_stage_available,
    workflow_stage_statuses,
)


APP_PATH = Path(__file__).resolve().parents[1] / "Data_Explorer.py"


def test_workflow_statuses_track_successful_actions_and_data_version():
    dataframe = pd.DataFrame({"Category": ["A", "B"], "Amount": [1, 2]})
    state = {"df": dataframe, "data_version": 3}

    statuses = workflow_stage_statuses(state, current_stage="profile")
    assert len(statuses) == 6
    assert statuses["upload"] == COMPLETED
    assert statuses["profile"] == IN_PROGRESS
    assert statuses["clean"] == NOT_STARTED
    assert statuses["validate"] == NOT_STARTED
    assert statuses["explore"] == NOT_STARTED
    assert statuses["export"] == NOT_STARTED
    assert workflow_stage_available(state, "profile")
    assert not workflow_stage_available(state, "clean")
    assert workflow_stage_available(state, "validate")
    assert not workflow_stage_available(state, "export")

    mark_workflow_stage_complete(state, "profile")
    statuses = workflow_stage_statuses(state, current_stage="profile")
    assert statuses["profile"] == COMPLETED
    assert statuses["clean"] == IN_PROGRESS
    assert workflow_stage_available(state, "clean")

    mark_workflow_stage_complete(state, "clean")
    statuses = workflow_stage_statuses(state)
    assert statuses["clean"] == COMPLETED

    bump_data_version(state, dataframe)
    statuses = workflow_stage_statuses(state)
    assert statuses["upload"] == COMPLETED
    assert statuses["profile"] == NOT_STARTED
    assert statuses["clean"] == NOT_STARTED


def test_workflow_keeps_six_stages_and_never_completes_unimplemented_actions():
    assert [stage[0] for stage in WORKFLOW_STAGES] == [
        "upload",
        "profile",
        "clean",
        "validate",
        "explore",
        "export",
    ]
    state = {"df": pd.DataFrame({"Value": [1]}), "data_version": 1}
    statuses = workflow_stage_statuses(state)
    assert statuses["validate"] == NOT_STARTED
    assert statuses["export"] == NOT_STARTED


def test_workflow_state_and_active_data_survive_page_navigation():
    dataframe = pd.DataFrame({"Category": ["A", "B", "A"], "Amount": [1, 2, 3]})
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = dataframe.copy(deep=True)
    at.session_state["source"] = "workflow test fixture"
    at.session_state["data_version"] = 1
    at.session_state["data_version_df_id"] = id(at.session_state["df"])

    at.run()
    assert not at.exception
    assert at.session_state["guided_workflow"]["completed"] == ["upload"]

    at.switch_page("pages/1_Data_Quality.py").run()
    assert not at.exception
    at.button(key="dq_run_analysis").click().run()
    assert not at.exception
    assert "profile" in at.session_state["guided_workflow"]["completed"]

    at.switch_page("pages/3_Charts.py").run()
    assert not at.exception
    assert "explore" in at.session_state["guided_workflow"]["completed"]
    pdt.assert_frame_equal(at.session_state["df"], dataframe)

    at.switch_page("pages/2_Editor.py").run()
    assert not at.exception
    at.switch_page("Data_Explorer.py").run()
    assert not at.exception
    pdt.assert_frame_equal(at.session_state["edited_df"], dataframe)
    assert "profile" in at.session_state["guided_workflow"]["completed"]
    assert "explore" in at.session_state["guided_workflow"]["completed"]


def test_workflow_marks_clean_only_after_apply_and_resets_on_undo():
    dataframe = pd.DataFrame({"Category": ["A", "A", "B"], "Amount": [1, 1, 2]})
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = dataframe.copy(deep=True)
    at.session_state["source"] = "workflow cleaning fixture"
    at.run()
    assert not at.exception

    at.switch_page("pages/1_Data_Quality.py").run()
    assert not at.exception
    at.button(key="dq_run_analysis").click().run()
    assert not at.exception
    assert "profile" in at.session_state["guided_workflow"]["completed"]
    assert "clean" not in at.session_state["guided_workflow"]["completed"]

    at.checkbox(key="dq_remove_duplicates").set_value(True).run()
    assert not at.exception
    at.button(key="dq_run_preview").click().run()
    assert not at.exception
    assert "clean" not in at.session_state["guided_workflow"]["completed"]

    at.button(key="dq_apply_cleaning").click().run()
    assert not at.exception
    assert "clean" in at.session_state["guided_workflow"]["completed"]
    assert "profile" not in at.session_state["guided_workflow"]["completed"]

    at.button(key="dq_undo_cleaning").click().run()
    assert not at.exception
    assert "clean" not in at.session_state["guided_workflow"]["completed"]
    assert "profile" not in at.session_state["guided_workflow"]["completed"]


def _open_editor_with_completed_workflow(dataframe):
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["df"] = dataframe.copy(deep=True)
    at.session_state["source"] = "editor version fixture"
    at.session_state["data_version"] = 5
    at.session_state["data_version_df_id"] = id(at.session_state["df"])
    at.session_state["guided_workflow"] = {
        "data_version": 5,
        "completed": ["upload", "profile", "explore"],
    }
    at.run()
    assert not at.exception
    at.switch_page("pages/2_Editor.py").run()
    assert not at.exception
    return at


def test_editor_cell_edits_bump_once_and_invalidate_workflow_progress():
    dataframe = pd.DataFrame({"Category": ["A", "B"], "Amount": [10, 20]})
    at = _open_editor_with_completed_workflow(dataframe)

    assert at.session_state["data_version"] == 5
    assert at.session_state["guided_workflow"]["completed"] == [
        "explore",
        "profile",
        "upload",
    ]

    at.session_state["dq_analysis"] = {"report": "stale"}
    at.session_state["dq_preview"] = {"summary": "stale"}
    at.session_state["editor"] = {
        "edited_rows": {0: {"Amount": 10}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert at.session_state["data_version"] == 5
    assert "profile" in at.session_state["guided_workflow"]["completed"]

    at.session_state["editor"] = {
        "edited_rows": {0: {"Amount": 99}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert at.session_state["data_version"] == 6
    assert at.session_state["data_version_df_id"] == id(at.session_state["edited_df"])
    assert at.session_state["guided_workflow"]["data_version"] == 6
    assert at.session_state["guided_workflow"]["completed"] == ["upload"]
    assert "dq_analysis" not in at.session_state
    assert "dq_preview" not in at.session_state
    assert at.session_state["edited_df"].loc[0, "Amount"] == 99

    at.run()
    assert not at.exception
    assert at.session_state["data_version"] == 6


def test_editor_column_commit_bumps_once_but_cancelled_delete_does_not():
    dataframe = pd.DataFrame({"Category": ["A"], "Amount": [10]})
    at = _open_editor_with_completed_workflow(dataframe)
    version_before_delete = at.session_state["data_version"]

    at.button(key="delete_columns_submit").click().run()
    assert not at.exception
    assert at.session_state["data_version"] == version_before_delete

    at.multiselect(key="w_delete_column_positions").set_value([1])
    at.button(key="delete_columns_submit").click().run()
    assert not at.exception
    assert at.session_state["data_version"] == version_before_delete + 1
    assert at.session_state["data_version_df_id"] == id(at.session_state["edited_df"])
    assert at.session_state["guided_workflow"]["data_version"] == version_before_delete + 1
    assert at.session_state["guided_workflow"]["completed"] == ["upload"]
    assert at.session_state["edited_df"].columns.tolist() == ["Category"]

    at.multiselect(key="w_delete_column_positions").set_value([0])
    at.button(key="delete_columns_submit").click().run()
    assert not at.exception
    assert at.session_state["data_version"] == version_before_delete + 1
    assert any("at least one column" in error.value for error in at.error)

    at.run()
    assert not at.exception
    assert at.session_state["data_version"] == version_before_delete + 1
