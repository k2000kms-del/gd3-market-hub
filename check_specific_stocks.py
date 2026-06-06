import FinanceDataReader as fdr
from data_collector import _classify_sector

df_ks = fdr.StockListing('KOSPI')
df_kq = fdr.StockListing('KOSDAQ')
df_all = fdr.StockListing('KRX')

targets = {
    '066570': 'LG전자',
    '009150': '삼성전기',
    '402340': 'SK스퀘어',
    '011070': 'LG이노텍'
}

print("Code | Name | FDR Sector | FDR Industry | Classified Sector")
for code, name in targets.items():
    row = df_all[df_all['Code'] == code]
    if not row.empty:
        fdr_sector = row.iloc[0].get('Sector', '')
        fdr_industry = row.iloc[0].get('Industry', '')
        classified = _classify_sector(code, name, fdr_sector, fdr_industry)
        print(f"{code} | {name} | {fdr_sector} | {fdr_industry} | {classified}")
    else:
        print(f"{code} | {name} | Not Found in KRX")
