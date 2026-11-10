import pandas as pd
import pandas.testing as pdt

from components.data_quality import (
    bump_data_version as legacy_bump_data_version,
    ensure_data_version as legacy_ensure_data_version,
)
from components.session_data import (
    apply_cleaned_dataframe,
    bump_data_version,
    ensure_data_version,
    get_active_dataframe,
    get_source_dataframe,
    replace_source_dataframe,
    set_active_dataframe,
    undo_cleaned_dataframe,
)


def test_get_source_dataframe_returns_the_stored_source_without_copying():
    source_df = pd.DataFrame({"value": [1, 2]})
    state = {"df": source_df}

    result = get_source_dataframe(state)

    assert result is source_df
    pdt.assert_frame_equal(result, pd.DataFrame({"value": [1, 2]}))


def test_get_active_dataframe_falls_back_to_the_source_dataframe():
    source_df = pd.DataFrame({"value": [1, 2]})
    state = {"df": source_df}

    assert get_active_dataframe(state) is source_df


def test_get_active_dataframe_prefers_the_edited_dataframe():
    source_df = pd.DataFrame({"value": [1, 2]})
    edited_df = pd.DataFrame({"value": [1, 3]})
    state = {"df": source_df, "edited_df": edited_df}

    assert get_active_dataframe(state) is edited_df


def test_set_active_dataframe_stores_the_same_object_without_mutating_data():
    source_df = pd.DataFrame({"value": [1, 2]})
    active_df = pd.DataFrame({"value": [3, 4]})
    original_active_df = active_df.copy(deep=True)
    state = {"df": source_df}

    set_active_dataframe(state, active_df)

    assert state["edited_df"] is active_df
    assert get_active_dataframe(state) is active_df
    pdt.assert_frame_equal(active_df, original_active_df)
    pdt.assert_frame_equal(source_df, pd.DataFrame({"value": [1, 2]}))


def test_replace_source_updates_metadata_and_clears_the_edited_override():
    old_source = pd.DataFrame({"value": [1]})
    old_edited = pd.DataFrame({"value": [2]})
    new_source = pd.DataFrame({"region": ["North", "South"]})
    state = {
        "df": old_source,
        "edited_df": old_edited,
        "source": "old.csv",
        "file_key": "old.csv-10-id1",
    }
    old_source_before = old_source.copy(deep=True)
    old_edited_before = old_edited.copy(deep=True)
    new_source_before = new_source.copy(deep=True)

    replace_source_dataframe(
        state,
        new_source,
        source="new.csv",
        file_key="new.csv-20-id2",
    )

    assert state["df"] is new_source
    assert state["source"] == "new.csv"
    assert state["file_key"] == "new.csv-20-id2"
    assert "edited_df" not in state
    assert get_active_dataframe(state) is new_source
    pdt.assert_frame_equal(old_source, old_source_before)
    pdt.assert_frame_equal(old_edited, old_edited_before)
    pdt.assert_frame_equal(new_source, new_source_before)


def test_replacing_source_without_a_file_key_clears_a_previous_upload_key():
    new_source = pd.DataFrame({"value": [3]})
    state = {
        "df": pd.DataFrame({"value": [1]}),
        "edited_df": pd.DataFrame({"value": [2]}),
        "source": "old.csv",
        "file_key": "old.csv-10-id1",
    }

    replace_source_dataframe(state, new_source, source="demo data")

    assert state["df"] is new_source
    assert state["source"] == "demo data"
    assert "file_key" not in state
    assert "edited_df" not in state


def test_bump_data_version_increments_and_clears_quality_results():
    active_df = pd.DataFrame({"value": [1]})
    state = {
        "data_version": 2,
        "dq_analysis": {"report": "old"},
        "dq_preview": {"summary": "old"},
    }

    version = bump_data_version(state, active_df)

    assert version == 3
    assert state["data_version"] == 3
    assert state["data_version_df_id"] == id(active_df)
    assert "dq_analysis" not in state
    assert "dq_preview" not in state


def test_ensure_data_version_initializes_state():
    active_df = pd.DataFrame({"value": [1]})
    state = {
        "dq_analysis": {"report": "old"},
        "dq_preview": {"summary": "old"},
    }

    version = ensure_data_version(state, active_df)

    assert version == 1
    assert state["data_version"] == 1
    assert state["data_version_df_id"] == id(active_df)
    assert "dq_analysis" not in state
    assert "dq_preview" not in state


def test_ensure_data_version_does_not_increment_for_the_same_dataframe():
    active_df = pd.DataFrame({"value": [1]})
    analysis = {"report": "current"}
    preview = {"summary": "current"}
    state = {
        "data_version": 4,
        "data_version_df_id": id(active_df),
        "dq_analysis": analysis,
        "dq_preview": preview,
    }

    version = ensure_data_version(state, active_df)

    assert version == 4
    assert state["dq_analysis"] is analysis
    assert state["dq_preview"] is preview


def test_ensure_data_version_increments_and_invalidates_after_replacement():
    previous_df = pd.DataFrame({"value": [1]})
    active_df = pd.DataFrame({"value": [2]})
    state = {
        "data_version": 4,
        "data_version_df_id": id(previous_df),
        "dq_analysis": {"report": "old"},
        "dq_preview": {"summary": "old"},
    }

    version = ensure_data_version(state, active_df)

    assert version == 5
    assert state["data_version_df_id"] == id(active_df)
    assert "dq_analysis" not in state
    assert "dq_preview" not in state


def test_data_quality_module_reexports_data_version_helpers():
    assert legacy_bump_data_version is bump_data_version
    assert legacy_ensure_data_version is ensure_data_version


def test_apply_cleaned_dataframe_saves_source_reference_and_invalidates_quality_state():
    source_df = pd.DataFrame({"value": [1, 1]})
    cleaned_df = pd.DataFrame({"value": [1]})
    analysis = {"report": "stale"}
    preview = {"summary": "stale"}
    state = {
        "df": source_df,
        "data_version": 3,
        "data_version_df_id": id(source_df),
        "dq_analysis": analysis,
        "dq_preview": preview,
    }
    source_before = source_df.copy(deep=True)
    cleaned_before = cleaned_df.copy(deep=True)

    apply_cleaned_dataframe(state, cleaned_df)

    assert state["dq_undo"]["had_edited_df"] is False
    assert state["dq_undo"]["previous_df"] is source_df
    assert state["edited_df"] is cleaned_df
    assert get_active_dataframe(state) is cleaned_df
    assert state["data_version"] == 4
    assert state["data_version_df_id"] == id(cleaned_df)
    assert "dq_analysis" not in state
    assert "dq_preview" not in state
    pdt.assert_frame_equal(source_df, source_before)
    pdt.assert_frame_equal(cleaned_df, cleaned_before)


def test_apply_cleaned_dataframe_preserves_existing_edited_dataframe_reference():
    source_df = pd.DataFrame({"source": [1]})
    previous_edited_df = pd.DataFrame({"value": [1, 1]})
    cleaned_df = pd.DataFrame({"value": [1]})
    state = {
        "df": source_df,
        "edited_df": previous_edited_df,
        "data_version": 5,
        "data_version_df_id": id(previous_edited_df),
    }

    apply_cleaned_dataframe(state, cleaned_df)

    assert state["dq_undo"]["had_edited_df"] is True
    assert state["dq_undo"]["previous_df"] is previous_edited_df
    assert state["edited_df"] is cleaned_df
    assert state["data_version"] == 6


def test_undo_cleaned_dataframe_removes_override_when_apply_started_from_source():
    source_df = pd.DataFrame({"value": [1, 1]})
    cleaned_df = pd.DataFrame({"value": [1]})
    state = {
        "df": source_df,
        "edited_df": cleaned_df,
        "dq_undo": {"had_edited_df": False, "previous_df": source_df},
        "data_version": 4,
        "data_version_df_id": id(cleaned_df),
        "dq_analysis": {"report": "stale"},
        "dq_preview": {"summary": "stale"},
    }
    source_before = source_df.copy(deep=True)

    restored_df = undo_cleaned_dataframe(state)

    assert restored_df is source_df
    assert "edited_df" not in state
    assert "dq_undo" not in state
    assert state["data_version"] == 5
    assert state["data_version_df_id"] == id(source_df)
    assert "dq_analysis" not in state
    assert "dq_preview" not in state
    pdt.assert_frame_equal(source_df, source_before)


def test_undo_cleaned_dataframe_restores_existing_edited_dataframe_reference():
    source_df = pd.DataFrame({"source": [1]})
    previous_edited_df = pd.DataFrame({"value": [1, 1]})
    cleaned_df = pd.DataFrame({"value": [1]})
    state = {
        "df": source_df,
        "edited_df": cleaned_df,
        "dq_undo": {"had_edited_df": True, "previous_df": previous_edited_df},
        "data_version": 8,
        "data_version_df_id": id(cleaned_df),
    }

    restored_df = undo_cleaned_dataframe(state)

    assert restored_df is previous_edited_df
    assert state["edited_df"] is previous_edited_df
    assert "dq_undo" not in state
    assert state["data_version"] == 9
    assert state["data_version_df_id"] == id(previous_edited_df)
