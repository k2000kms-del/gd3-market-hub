import os, requests
from dotenv import load_dotenv

load_dotenv()
APP_KEY = os.environ.get('KIS_APP_KEY')
APP_SECRET = os.environ.get('KIS_APP_SECRET')
URL_BASE = "https://openapi.koreainvestment.com:9443"

def get_token():
    headers = {'content-type': 'application/json'}
    body = {
        'grant_type': 'client_credentials',
        'appkey': APP_KEY,
        'appsecret': APP_SECRET
    }
    res = requests.post(f'{URL_BASE}/oauth2/tokenP', headers=headers, json=body)
    return res.json().get('access_token')

def get_sector(token, code):
    headers = {
        'Content-Type': 'application/json',
        'authorization': f'Bearer {token}',
        'appkey': APP_KEY,
        'appsecret': APP_SECRET,
        'tr_id': 'FHKST01010100',
    }
    params = {
        'FID_COND_MRKT_DIV_CODE': 'J',
        'FID_INPUT_ISCD': code,
    }
    res = requests.get(f'{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price', headers=headers, params=params)
    return res.json().get('output', {}).get('bstp_kor_isnm', '')

token = get_token()
print(get_sector(token, '005930')) # Samsung Electronics
