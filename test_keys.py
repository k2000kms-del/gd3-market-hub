import os
import streamlit as st

def test_keys():
    kis_key = os.environ.get("KIS_APP_KEY", "")
    kis_sec = os.environ.get("KIS_APP_SECRET", "")
    print("os.environ KIS_APP_KEY:", bool(kis_key))
    
    try:
        from streamlit import secrets
        print("st.secrets KIS_APP_KEY:", bool(secrets.get("KIS_APP_KEY")))
    except Exception as e:
        print("st.secrets error:", e)

test_keys()
