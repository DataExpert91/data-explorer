# Editor page.
#
# Works on the FULL table (session_state["edited_df"]): edit cells, add or
# delete rows and columns, mark protected columns, download the result.
# Edits survive leaving the page and coming back.

from collections import Counter
import io

import streamlit as st

from components.session_data import get_active_dataframe, set_active_dataframe

st.title("Editor")

if "df" not in st.session_state:
    st.warning("No data loaded. Please open the main page first.")
    st.stop()

# the working copy of the table
if "edited_df" not in st.session_state:
    set_active_dataframe(
        st.session_state,
        get_active_dataframe(st.session_state).copy(),
    )

# While the user stays on this page, the editor must always receive the SAME
# base table. When the user arrives (the editor has no state yet), we restart
# the base from the saved table.
if "editor" not in st.session_state or "editor_base" not in st.session_state:
    st.session_state["editor_base"] = get_active_dataframe(st.session_state).copy()


def commit(new_df):
    """Make new_df the current table and restart the editor from it."""
    set_active_dataframe(st.session_state, new_df)
    st.session_state["editor_base"] = new_df.copy()
    st.session_state.pop("editor", None)


current = get_active_dataframe(st.session_state)
column_positions = list(range(len(current.columns)))
column_label_counts = Counter(str(column) for column in current.columns)


def _column_schema(dataframe):
    return tuple((type(column).__name__, repr(column)) for column in dataframe.columns)


def _format_column_position(position):
    column = current.columns[position]
    label = str(column)
    if column_label_counts[label] > 1 or not isinstance(column, str):
        return f"{label} ({type(column).__name__}, column {position + 1})"
    return label


current_schema = _column_schema(current)
saved_protected = st.session_state.get("protected_positions")
if not isinstance(saved_protected, dict) or saved_protected.get("schema") != current_schema:
    # Migrate the previous label-based state. A saved duplicate label protected
    # every matching column under the old behavior.
    legacy_protected = st.session_state.pop(
        "w_protected", st.session_state.get("protected_cols", ["Row ID"])
    )
    if not isinstance(legacy_protected, list):
        legacy_protected = []
    protected_positions = [
        position
        for position, column in enumerate(current.columns)
        if column in legacy_protected
    ]
    st.session_state["protected_positions"] = {
        "schema": current_schema,
        "positions": protected_positions,
    }
    st.session_state["w_protected_positions"] = protected_positions
else:
    protected_positions = [
        position
        for position in saved_protected.get("positions", [])
        if isinstance(position, int) and position in column_positions
    ]
    if "w_protected_positions" not in st.session_state:
        st.session_state["w_protected_positions"] = protected_positions
    else:
        widget_positions = st.session_state["w_protected_positions"]
        if not isinstance(widget_positions, list):
            widget_positions = []
        protected_positions = [
            position
            for position in widget_positions
            if isinstance(position, int) and position in column_positions
        ]
        if protected_positions != widget_positions:
            st.session_state["w_protected_positions"] = protected_positions


def _save_protected_positions(dataframe, positions, update_widget=True):
    valid_positions = [
        position
        for position in positions
        if isinstance(position, int) and 0 <= position < len(dataframe.columns)
    ]
    schema = _column_schema(dataframe)
    st.session_state["protected_positions"] = {
        "schema": schema,
        "positions": valid_positions,
    }
    if update_widget:
        st.session_state["w_protected_positions"] = valid_positions
    st.session_state["protected_cols"] = [
        dataframe.columns[position] for position in valid_positions
    ]

# ---------- Manage columns ----------
with st.expander("Manage columns"):
    with st.form("add_column_form", clear_on_submit=True):
        new_name = st.text_input("New column name")
        new_type = st.selectbox("Column type", ["Text", "Number"])
        add_clicked = st.form_submit_button("Add column")

    if add_clicked:
        name = new_name.strip()
        if not name:
            st.error("Please enter a column name.")
        elif name in current.columns:
            st.error(f"Column '{name}' already exists.")
        else:
            updated = current.copy()
            updated[name] = "" if new_type == "Text" else 0.0
            _save_protected_positions(
                updated,
                st.session_state.get("w_protected_positions", protected_positions),
            )
            commit(updated)
            st.rerun()

    with st.form("delete_columns_form", clear_on_submit=True):
        to_delete = st.multiselect(
            "Columns to delete",
            options=column_positions,
            format_func=_format_column_position,
            key="w_delete_column_positions",
        )
        delete_clicked = st.form_submit_button(
            "Delete selected columns", key="delete_columns_submit"
        )

    if delete_clicked and to_delete:
        remaining_positions = [
            position for position in column_positions if position not in to_delete
        ]
        if not remaining_positions:
            st.error("A table needs at least one column.")
        else:
            updated = current.iloc[:, remaining_positions].copy()
            selected_protected = st.session_state.get(
                "w_protected_positions", protected_positions
            )
            updated_protected = [
                new_position
                for new_position, old_position in enumerate(remaining_positions)
                if old_position in selected_protected
            ]
            _save_protected_positions(updated, updated_protected)
            commit(updated)
            st.rerun()

# ---------- Protected columns ----------
protected_positions = st.sidebar.multiselect(
    "Protected columns (cannot be edited)",
    options=column_positions,
    key="w_protected_positions",
    format_func=_format_column_position,
)
_save_protected_positions(current, protected_positions, update_widget=False)

# ---------- The editor ----------
editor_base = st.session_state["editor_base"]
original_columns = editor_base.columns.copy()
display_columns = list(original_columns)
stringified_columns = [str(column) for column in original_columns]
needs_temporary_labels = (
    not original_columns.is_unique
    or any(not isinstance(column, str) for column in original_columns)
    or len(set(stringified_columns)) != len(stringified_columns)
)
if needs_temporary_labels:
    display_columns = [f"col_{position}" for position in range(len(original_columns))]

# Streamlit's editor needs unique string labels. Only its shallow display copy
# receives temporary labels; editor_base and the active dataframe retain theirs.
display_base = editor_base.copy(deep=False)
display_base.columns = display_columns
protected_display = [
    display_columns[position] for position in protected_positions
]

edited_display_df = st.data_editor(
    display_base,
    disabled=protected_display,
    num_rows="dynamic",
    key="editor",
)

edited_df = edited_display_df.copy(deep=False)
edited_df.columns = original_columns

# save the edits so they survive leaving the page
set_active_dataframe(st.session_state, edited_df)

st.caption(f"{edited_df.shape[0]} rows, {edited_df.shape[1]} columns")

# ---------- Download ----------
st.subheader("Download")

# CSV is fast, so the button is always there.
# utf-8-sig makes Excel show non-English letters correctly.
st.download_button(
    "Download CSV",
    data=edited_df.to_csv(index=False).encode("utf-8-sig"),
    file_name="edited_data.csv",
    mime="text/csv",
)

# Building an Excel file takes a couple of seconds, so it is done on request only.
if st.button("Prepare Excel file"):
    with st.spinner("Building the Excel file..."):
        buffer = io.BytesIO()
        edited_df.to_excel(buffer, index=False, engine="openpyxl")
    st.download_button(
        "Download Excel",
        data=buffer.getvalue(),
        file_name="edited_data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
