import streamlit as st
import os

try:
    from supabase import create_client
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
    res = supabase.table("portfolio").select("*").limit(1).execute()
    print("Portfolio table exists. Result:", res.data)
except Exception as e:
    print("Error:", e)
