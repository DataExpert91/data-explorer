# Editor page.
#
# Works on the FULL table (session_state["edited_df"]): edit cells, add or
# delete rows and columns, mark protected columns, download the result.
# Edits survive leaving the page and coming back.

from collections import Counter
import io

import streamlit as st

st.title("Editor")

if "df" not in st.session_state:
    st.warning("No data loaded. Please open the main page first.")
    st.stop()

# the working copy of the table
if "edited_df" not in st.session_state:
    st.session_state["edited_df"] = st.session_state["df"].copy()

# While the user stays on this page, the editor must always receive the SAME
# base table. When the user arrives (the editor has no state yet), we restart
# the base from the saved table.
if "editor" not in st.session_state or "editor_base" not in st.session_state:
    st.session_state["editor_base"] = st.session_state["edited_df"].copy()


def commit(new_df):
    """Make new_df the current table and restart the editor from it."""
    st.session_state["edited_df"] = new_df
    st.session_state["editor_base"] = new_df.copy()
    st.session_state.pop("editor", None)


current = st.session_state["edited_df"]

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
            commit(updated)
            st.rerun()

    with st.form("delete_columns_form"):
        to_delete = st.multiselect("Columns to delete", options=list(current.columns))
        delete_clicked = st.form_submit_button("Delete selected columns")

    if delete_clicked and to_delete:
        if len(to_delete) >= len(current.columns):
            st.error("A table needs at least one column.")
        else:
            updated = current.drop(columns=to_delete)
            # a deleted column cannot stay in the protected list
            st.session_state["w_protected"] = [
                c for c in st.session_state.get("w_protected", [])
                if c in updated.columns
            ]
            commit(updated)
            st.rerun()

# ---------- Protected columns ----------
# the choice is saved, because widgets forget their value when the page is left
if "w_protected" not in st.session_state:
    wanted = st.session_state.get("protected_cols", ["Row ID"])
    st.session_state["w_protected"] = [c for c in wanted if c in current.columns]


protected_label_strings = [str(column) for column in current.columns]
protected_label_counts = Counter(protected_label_strings)


def _format_protected_column(column):
    label = str(column)
    if protected_label_counts[label] > 1:
        position = current.columns.get_loc(column)
        if isinstance(position, int):
            return f"{label} ({type(column).__name__}, column {position + 1})"
    return label


protected = st.sidebar.multiselect(
    "Protected columns (cannot be edited)",
    options=list(current.columns),
    key="w_protected",
    format_func=_format_protected_column,
)
st.session_state["protected_cols"] = protected

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
    display_columns[position]
    for position, column in enumerate(original_columns)
    if column in protected
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
st.session_state["edited_df"] = edited_df

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
