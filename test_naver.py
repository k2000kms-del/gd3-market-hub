import requests
r = requests.get("https://api.finance.naver.com/siseJson.naver?symbol=005930&requestType=0&timeframe=minute&count=5")
print(r.text)
