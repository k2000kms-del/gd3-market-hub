import requests
import xml.etree.ElementTree as ET

url = "https://fchart.stock.naver.com/sise.nhn?symbol=005930&timeframe=minute&count=10&requestType=0"
r = requests.get(url)
print(r.text)
