import pandas as pd
import streamlit as st

st.title("Editor")

if "df" not in st.session_state:
    st.warning("No data loaded. Please go to the main page and upload a file first.")
else:
    df = st.session_state["df"]
    st.dataframe(df)