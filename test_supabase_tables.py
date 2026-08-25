import streamlit as st
import requests

url = f"{st.secrets['SUPABASE_URL']}/rest/v1/"
headers = {
    "apikey": st.secrets["SUPABASE_ANON_KEY"],
    "Authorization": f"Bearer {st.secrets['SUPABASE_ANON_KEY']}"
}
r = requests.get(url, headers=headers)
print(r.json())
