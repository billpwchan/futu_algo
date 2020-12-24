#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

from datetime import datetime

import trading_engine


def daily_update_1M(futu_trade):
    # Daily Update HSI Constituents & Customized Stocks
    hsi_constituents = trading_engine.get_hsi_constituents(
        './data/HSI.Constituents/HSI_constituents_2020-12-22.json')
    customized_stocks = trading_engine.get_customized_stocks(
        f'./data/Customized/Customized_Stocks_{str(datetime.today().date())}.json')
    for stock_code in hsi_constituents:
        futu_trade.update_1M_data(stock_code)
    for stock_code in customized_stocks:
        futu_trade.update_1M_data(stock_code)


def main():
    # Initialization Connection
    futu_trade = trading_engine.FutuTrade()
    try:
        trading_engine.update_customized_stocks()
        daily_update_1M(futu_trade=futu_trade)

        # futu_trade.stock_price_subscription(['HK.00001', 'HK.00003'])




    finally:
        ret, data = futu_trade.quote_ctx.query_subscription()
        trading_engine.display_result(ret, data)
        ret, data = futu_trade.quote_ctx.get_history_kl_quota(get_detail=True)  # 设置True代表需要返回详细的拉取历史K 线的记录
        trading_engine.display_result(ret, data)
        futu_trade.quote_ctx.close()


if __name__ == '__main__':
    main()
