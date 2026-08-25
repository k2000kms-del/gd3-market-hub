import streamlit as st
import requests

gh_token = st.secrets.get("GITHUB_TOKEN")
url = "https://api.github.com/repos/k2000kms-del/gd3-market-hub/contents/data/my_portfolio.json"
headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
r = requests.get(url, headers=headers)
print(r.status_code)
if r.status_code == 200:
    print(r.json().get('sha'))
else:
    print(r.text)
