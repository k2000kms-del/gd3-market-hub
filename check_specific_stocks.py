import requests
import pandas as pd
from html.parser import HTMLParser

class KINDHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_td = False
        self.current_row = []
        self.rows = []
        self.temp_data = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
        elif tag == "tr" and self.in_table:
            self.in_tr = True
            self.current_row = []
        elif tag in ["td", "th"] and self.in_tr:
            self.in_td = True
            self.temp_data = ""

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        elif tag == "tr" and self.in_table:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
        elif tag in ["td", "th"] and self.in_tr:
            self.in_td = False
            self.current_row.append(self.temp_data.strip())

    def handle_data(self, data):
        if self.in_td:
            self.temp_data += data

def get_krx_sectors():
    try:
        url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
        res = requests.get(url)
        res.encoding = 'EUC-KR'
        parser = KINDHtmlParser()
        parser.feed(res.text)
        if len(parser.rows) > 1:
            headers = parser.rows[0]
            data_rows = parser.rows[1:]
            df = pd.DataFrame(data_rows, columns=headers)
            if '종목코드' in df.columns:
                df['Symbol'] = df['종목코드'].astype(str).str.zfill(6)
            return df
    except Exception as e:
        print(f"Error: {e}")
    return pd.DataFrame()

df_sectors = get_krx_sectors()

targets = {
    '066570': 'LG전자',
    '009150': '삼성전기',
    '402340': 'SK스퀘어',
    '011070': 'LG이노텍'
}

with open('output_sectors.txt', 'w', encoding='utf-8') as f:
    f.write("Code | Name | KIND Sector | KIND Industry\n")
    for code, name in targets.items():
        row = df_sectors[df_sectors['Symbol'] == code]
        if not row.empty:
            sector = row.iloc[0].get('업종', '')
            industry = row.iloc[0].get('주요제품', '')
            f.write(f"{code} | {name} | {sector} | {industry}\n")
        else:
            f.write(f"{code} | {name} | Not Found\n")
