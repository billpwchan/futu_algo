import datetime

from futu import *


def display_result(ret, data):
    if ret == RET_OK:
        print(data)
    else:
        print('error:', data)


def save_historical_data(quote_ctx, stock_code, start_date, end_date, k_type):
    ret, data, page_req_key = quote_ctx.request_history_kline(stock_code, start=start_date,
                                                              end=end_date,
                                                              ktype=k_type, autype=AuType.QFQ,
                                                              fields=[KL_FIELD.ALL],
                                                              max_count=1000, page_req_key=None,
                                                              extended_time=False)
    out_dir = f'./data/{stock_code}'
    if not os.path.exists(out_dir):
        os.mkdir(out_dir)
    data.to_csv(f'./data/{stock_code}/{stock_code}_{start_date}_1M.csv', index=False)
    time.sleep(0.6)


def get_indices(input_file):
    indices = pd.read_excel(input_file, index_col=0)
    indices = indices.iloc[1::2].index.tolist()  # even
    indices = ['.'.join(item.split('.')[::-1]) for item in indices]
    with open(f'./data/Indices/indices_{datetime.today().date()}.json', 'w+') as f:
        json.dump(indices, f)
