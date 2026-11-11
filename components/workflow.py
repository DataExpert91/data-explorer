"""Small session-state helpers and navigation for the guided workflow."""

from __future__ import annotations

import streamlit as st

WORKFLOW_STATE_KEY = "guided_workflow"
COMPLETED = "Completed"
IN_PROGRESS = "In Progress"
NOT_STARTED = "Not Started"

WORKFLOW_STAGES = (
    ("upload", "Upload Data", "Data_Explorer.py"),
    ("profile", "Profile Data", "pages/1_Data_Quality.py"),
    ("clean", "Clean Data", "pages/1_Data_Quality.py"),
    ("validate", "Validate Data", "pages/1_Data_Quality.py"),
    ("explore", "Explore Data", "pages/3_Charts.py"),
    ("export", "Export Results", None),
)
_STAGE_IDS = {stage_id for stage_id, _, _ in WORKFLOW_STAGES}


def sync_workflow_state(state):
    """Reset data-dependent progress when the centralized data version changes."""
    try:
        version = int(state.get("data_version", 0))
    except (TypeError, ValueError):
        version = 0

    workflow = state.get(WORKFLOW_STATE_KEY)
    if not isinstance(workflow, dict) or workflow.get("data_version") != version:
        workflow = {"data_version": version, "completed": []}

    completed = set(workflow.get("completed", [])) & _STAGE_IDS
    if state.get("df") is not None:
        completed.add("upload")
    workflow["completed"] = sorted(completed)
    state[WORKFLOW_STATE_KEY] = workflow
    return workflow


def mark_workflow_stage_complete(state, stage_id):
    """Record a stage only after its caller confirms the action succeeded."""
    if stage_id not in _STAGE_IDS:
        raise ValueError(f"Unknown workflow stage: {stage_id}")
    workflow = sync_workflow_state(state)
    completed = set(workflow["completed"])
    completed.add(stage_id)
    workflow["completed"] = sorted(completed)


def clear_workflow_stage(state, stage_id):
    """Clear completion evidence that is no longer valid."""
    workflow = sync_workflow_state(state)
    workflow["completed"] = [
        completed for completed in workflow["completed"] if completed != stage_id
    ]


def workflow_stage_statuses(state, current_stage=None):
    """Return conservative status labels for the six workflow stages."""
    workflow = sync_workflow_state(state)
    completed = set(workflow["completed"])
    has_data = state.get("df") is not None
    statuses = {}

    for stage_id, _, _ in WORKFLOW_STAGES:
        if stage_id in completed:
            statuses[stage_id] = COMPLETED
        elif stage_id == "upload" and current_stage == "upload":
            statuses[stage_id] = IN_PROGRESS
        elif (
            stage_id == "profile"
            and has_data
            and current_stage in {"profile", "quality"}
        ):
            statuses[stage_id] = IN_PROGRESS
        elif (
            stage_id == "clean"
            and has_data
            and current_stage in {"profile", "quality"}
            and "profile" in completed
        ):
            statuses[stage_id] = IN_PROGRESS
        elif stage_id == "explore" and has_data and current_stage == "explore":
            statuses[stage_id] = IN_PROGRESS
        else:
            statuses[stage_id] = NOT_STARTED
    return statuses


def workflow_stage_available(state, stage_id):
    """Report whether the existing application exposes the stage action yet."""
    if stage_id not in _STAGE_IDS:
        raise ValueError(f"Unknown workflow stage: {stage_id}")
    workflow = sync_workflow_state(state)
    has_data = state.get("df") is not None

    if stage_id == "upload":
        return True
    if stage_id in {"profile", "explore", "validate"}:
        return has_data
    if stage_id == "clean":
        return has_data and "profile" in workflow["completed"]
    # These actions have no workflow implementation yet.
    return False


def render_workflow(current_stage=None):
    """Render six workflow stages and links to functionality already in the app."""
    state = st.session_state
    statuses = workflow_stage_statuses(state, current_stage)
    has_data = state.get("df") is not None

    with st.container(border=True):
        st.markdown("**Guided workflow**")
        columns = st.columns(3)
        for index, (stage_id, title, page) in enumerate(WORKFLOW_STAGES):
            column = columns[index % 3]
            with column:
                st.markdown(f"**{index + 1}. {title}**")
                st.caption(statuses[stage_id])
                if page is not None:
                    st.page_link(
                        page,
                        label="Open",
                        disabled=not workflow_stage_available(state, stage_id),
                    )
                else:
                    st.caption("Export workflow coming later")

        st.page_link(
            "pages/2_Editor.py",
            label="Open Editor",
            disabled=not has_data,
        )
