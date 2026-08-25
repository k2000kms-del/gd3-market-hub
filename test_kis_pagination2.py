import os
import requests
import json
import pandas as pd
import time

env_vars = {}
try:
    with open('.streamlit/secrets.toml', 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                env_vars[k.strip()] = v.strip().strip('"')
except Exception:
    pass

APP_KEY = env_vars.get('KIS_APP_KEY', env_vars.get('KIS_KEY', ''))
APP_SECRET = env_vars.get('KIS_APP_SECRET', env_vars.get('KIS_SECRET', ''))

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

def get_all_minutes(token, code):
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST03010200",
        "custtype": "P"
    }
    
    all_data = []
    target_time = "153000"
    
    for page in range(3):
        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": target_time,
            "FID_PW_DATA_INCU_YN": "Y"
        }
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        output2 = data.get('output2', [])
        
        print(f"Page {page} fetched {len(output2)} rows. First: {output2[0]['stck_cntg_hour']} Last: {output2[-1]['stck_cntg_hour']}")
        if not output2:
            break
            
        all_data.extend(output2)
        
        last_time = output2[-1]['stck_cntg_hour']
        # Decrement by 1 second to not get the exact same row again
        h = int(last_time[:2])
        m = int(last_time[2:4])
        s = int(last_time[4:])
        if s > 0: s -= 1
        else:
            s = 59
            if m > 0: m -= 1
            else:
                m = 59
                h -= 1
        
        target_time = f"{h:02d}{m:02d}{s:02d}"
        time.sleep(0.05)

if __name__ == "__main__":
    if APP_KEY:
        tok = get_token()
        get_all_minutes(tok, "005930")
