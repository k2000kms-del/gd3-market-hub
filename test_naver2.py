import requests
r = requests.get("https://api.finance.naver.com/siseJson.naver?symbol=005930&requestType=1&startTime=20260630090000&endTime=20260630153000&timeframe=minute")
print(r.text[:1000])
