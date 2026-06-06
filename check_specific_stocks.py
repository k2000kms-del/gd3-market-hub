import traceback

try:
    import FinanceDataReader as fdr
    df = fdr.StockListing('KRX')
    with open('output_sectors.txt', 'w', encoding='utf-8') as f:
        f.write("Columns:\n")
        f.write(str(list(df.columns)) + "\n\n")
        f.write("First row:\n")
        if not df.empty:
            f.write(str(df.iloc[0].to_dict()) + "\n")
        else:
            f.write("Empty DataFrame\n")
except Exception as e:
    with open('output_sectors.txt', 'w', encoding='utf-8') as f:
        f.write("CRASHED:\n")
        f.write(str(e) + "\n")
        f.write(traceback.format_exc() + "\n")
