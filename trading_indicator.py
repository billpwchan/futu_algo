#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import trading_utils


def daily_update_1M(futu_trade):
    # Daily Update HSI Constituents & Customized Stocks
    hsi_constituents = trading_utils.get_hsi_constituents(
        './data/HSI.Constituents/HSI_constituents_2020-12-22.json')
    customized_stocks = trading_utils.get_customized_stocks('./data/Customized/Customized_Stocks_2020-12-23.json')
    for stock_code in hsi_constituents:
        futu_trade.update_1M_data(stock_code)
    for stock_code in customized_stocks:
        futu_trade.update_1M_data(stock_code)


def main():
    # Initialization Connection
    futu_trade = trading_utils.FutuTrade()
    try:
        # input_data = pd.read_csv('./data/HK.00003/HK.00003_2020-12-23_1M.csv', index_col=None)
        # latest_data = pd.read_csv('./data/HK.00003/HK.00003_2020-12-24_1M.csv', index_col=None)
        # macd_cross = MACDCross(input_data)
        # macd_cross.parse_data(latest_data)

        futu_trade.stock_price_subscription('HK.00001')




    finally:
        ret, data = futu_trade.quote_ctx.query_subscription()
        trading_utils.display_result(ret, data)
        ret, data = futu_trade.quote_ctx.get_history_kl_quota(get_detail=True)  # 设置True代表需要返回详细的拉取历史K 线的记录
        trading_utils.display_result(ret, data)
        futu_trade.quote_ctx.close()


if __name__ == '__main__':
    main()
