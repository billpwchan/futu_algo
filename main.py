#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import glob

from futu import *

import trading_engine


def daily_update_data(futu_trade):
    # Daily Update HSI Constituents & Customized Stocks
    file_list = glob.glob(f"./data/HSI.Constituents/HSI_constituents_*.json")
    hsi_constituents = trading_engine.get_hsi_constituents(file_list[0])
    file_list = glob.glob(f"./data/Customized/Customized_Stocks_*.json")
    customized_stocks = trading_engine.get_customized_stocks(file_list[0])
    for stock_code in hsi_constituents:
        futu_trade.update_1D_data(stock_code)
        futu_trade.update_1M_data(stock_code)
    for stock_code in customized_stocks:
        futu_trade.update_1D_data(stock_code)
        futu_trade.update_1M_data(stock_code)


def daily_update_stocks():
    trading_engine.update_hsi_constituents()
    trading_engine.update_customized_stocks()


def main():
    # Initialization Connection
    futu_trade = trading_engine.FutuTrade()
    # Daily Update Data
    # daily_update_data(futu_trade=futu_trade)

    # Update ALl Data to Database
    # futu_trade.store_all_data_database()

    print(futu_trade.trade_ctx.position_list_query(code='HK.09988', pl_ratio_min=None, pl_ratio_max=None,
                                                   trd_env=TrdEnv.SIMULATE, acc_id=0, acc_index=0, refresh_cache=False)[
              1].empty)

    # Initialize Strategies
    # stock_list = ['HK.09988', 'HK.01211']
    # input_data = futu_trade.get_1M_data(stock_list=stock_list)
    # macd_cross = MACDCross(input_data=input_data)
    # futu_trade.stock_price_subscription(input_data, stock_list=stock_list, strategy=macd_cross, timeout=60)

    futu_trade.display_quota()


if __name__ == '__main__':
    main()
