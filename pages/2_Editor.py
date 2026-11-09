# Editor page.
#
# Works on a copy of the table (session_state["edited_df"]).
# The copy keeps the user's edits when they leave the page and come back.
# The edited table can be downloaded as CSV or Excel.

import io

import streamlit as st

st.title("Editor")

if "df" not in st.session_state:
    st.warning("No data loaded. Please open the main page first.")
else:
    # first visit: the working copy starts as the loaded table
    if "edited_df" not in st.session_state:
        st.session_state["edited_df"] = st.session_state["df"].copy()

    df = st.session_state["edited_df"]

    # sidebar: the user chooses which columns cannot be edited
    protected = st.sidebar.multiselect(
        "Protected columns (cannot be edited)",
        options=list(df.columns),
        default=["Row ID"] if "Row ID" in df.columns else [],
    )

    st.caption(f"{df.shape[0]} rows, {df.shape[1]} columns")

    edited_df = st.data_editor(
        df,
        disabled=protected,
        num_rows="dynamic",
        key="editor",
    )

    # save the edits so they survive leaving the page
    st.session_state["edited_df"] = edited_df

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