"""Small helpers for managing source and active dataframes in session state."""

from __future__ import annotations

import pandas as pd


def get_source_dataframe(state):
    """Return the dataframe loaded as the current source."""
    return state["df"]


def get_active_dataframe(state):
    """Return the edited dataframe when present, otherwise the source dataframe."""
    if "edited_df" in state:
        return state["edited_df"]
    return state["df"]


def set_active_dataframe(state, dataframe):
    """Publish a dataframe as the active edited version without copying it."""
    state["edited_df"] = dataframe


def adopt_equivalent_dataframe_reference(session_state, dataframe):
    """Track a known equivalent copy without treating it as a data change."""
    session_state["data_version_df_id"] = id(dataframe)


def replace_source_dataframe(state, dataframe, source, file_key=None):
    """Replace the source dataframe and clear the previous active override."""
    state["df"] = dataframe
    state["source"] = source
    state.pop("edited_df", None)
    if file_key is None:
        state.pop("file_key", None)
    else:
        state["file_key"] = file_key


def bump_data_version(
    session_state, active_df: pd.DataFrame | None = None
) -> int:
    """Record a controlled dataset replacement and discard quality results."""
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


def apply_cleaned_dataframe(session_state, dataframe):
    """Publish a cleaned dataframe and save the active dataframe for one-level undo."""
    previous_df = get_active_dataframe(session_state)
    session_state["dq_undo"] = {
        "had_edited_df": "edited_df" in session_state,
        "previous_df": previous_df,
    }
    set_active_dataframe(session_state, dataframe)
    bump_data_version(session_state, dataframe)


def undo_cleaned_dataframe(session_state):
    """Restore the dataframe saved by the most recent cleaning Apply."""
    undo = session_state.pop("dq_undo")
    if undo["had_edited_df"]:
        set_active_dataframe(session_state, undo["previous_df"])
    else:
        session_state.pop("edited_df", None)

    restored_df = get_active_dataframe(session_state)
    bump_data_version(session_state, restored_df)
    return restored_df
