import os
import requests
import json
import pandas as pd

# .env parsing
env_vars = {}
try:
    with open('.env', 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                env_vars[k.strip()] = v.strip()
except Exception:
    pass

APP_KEY = env_vars.get('KIS_APP_KEY', '')
APP_SECRET = env_vars.get('KIS_APP_SECRET', '')

def get_token():
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    res = requests.post(url, headers=headers, data=json.dumps(body))
    return res.json().get('access_token')

def get_kis_minute(token, code):
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST03010200",
        "custtype": "P"
    }
    params = {
        "FID_ETC_CLS_CODE": "",
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_HOUR_1": "153000",
        "FID_PW_DATA_INCU_YN": "Y"
    }
    res = requests.get(url, headers=headers, params=params)
    print("Status:", res.status_code)
    try:
        data = res.json()
        output2 = data.get('output2', [])
        print(f"Fetched {len(output2)} minute rows.")
        if len(output2) > 0:
            print("First:", output2[0])
            print("Last:", output2[-1])
    except Exception as e:
        print("Error", e)

if __name__ == "__main__":
    if APP_KEY:
        tok = get_token()
        get_kis_minute(tok, "005930")
    else:
        print("No KIS_APP_KEY in .env")
