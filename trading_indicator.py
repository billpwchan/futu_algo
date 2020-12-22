from futu import *
import json
import trading_utils


def update_1M_data(stock_code):
    for i in range(365 * 2):
        day = datetime.today() - timedelta(days=i)
        trading_utils.save_historical_data(quote_ctx, stock_code, str(day.date()), str(day.date()), KLType.K_1M)
        time.sleep(0.6)


# Initialization Connection
quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

try:
    # Execute Logics
    trading_utils.update_indices('./data/Indicies/AAstocks_StockList_2020-12-23.xlsx')

finally:
    ret, data = quote_ctx.query_subscription()
    trading_utils.display_result(ret, data)
    ret, data = quote_ctx.get_history_kl_quota(get_detail=True)  # 设置True代表需要返回详细的拉取历史K 线的记录
    trading_utils.display_result(ret, data)

    quote_ctx.close()  # 关闭当条连接，FutuOpenD会在1分钟后自动取消相应股票相应类型的订阅
