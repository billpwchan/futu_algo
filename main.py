#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import argparse
import glob

import trading_engine
from strategies.EMA_Ribbon import EMARibbon
from strategies.KDJ_Cross import KDJCross
from strategies.KDJ_MACD_Close import KDJMACDClose
from strategies.MACD_Cross import MACDCross
from strategies.RSI_Threshold import RSIThreshold
from strategies.Strategies import Strategies


def daily_update_data(futu_trade, force_update: bool = False):
    # Daily Update HSI Constituents & Customized Stocks
    file_list = glob.glob(f"./data/HSI.Constituents/HSI_constituents_*.json")
    hsi_constituents = trading_engine.get_hsi_constituents(file_list[0])
    file_list = glob.glob(f"./data/Customized/Customized_Stocks_*.json")
    customized_stocks = trading_engine.get_customized_stocks(file_list[0])
    for stock_code in hsi_constituents:
        futu_trade.update_1D_data(stock_code, force_update=force_update)
        futu_trade.update_1M_data(stock_code, force_update=force_update)
    for stock_code in customized_stocks:
        futu_trade.update_1D_data(stock_code, force_update=force_update)
        futu_trade.update_1M_data(stock_code, force_update=force_update)


def daily_update_stocks():
    trading_engine.update_hsi_constituents()
    trading_engine.update_customized_stocks()


def __init_strategy(strategy_name: str, input_data: dict) -> Strategies:
    switcher = {
        'EMA_Ribbon': EMARibbon(input_data=input_data),
        'KDJ_Cross': KDJCross(input_data=input_data),
        'KDJ_MACD_Close': KDJMACDClose(input_data=input_data),
        'MACD_Cross': MACDCross(input_data=input_data),
        'RSI_Threshold': RSIThreshold(input_data=input_data)
    }
    # Default return simplest MACD Cross Strategy
    return switcher.get(strategy_name, MACDCross(input_data=input_data))


def init_day_trading(futu_trade: trading_engine.FutuTrade, stock_list: list, strategy_name: str):
    input_data = futu_trade.get_data_realtime(stock_list, kline_num=100)
    strategy = __init_strategy(strategy_name=strategy_name, input_data=input_data)
    futu_trade.cur_kline_subscription(input_data, stock_list=stock_list, strategy=strategy, timeout=3600 * 12)


def main():
    # Initialize Argument Parser
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--update", help="Daily Update Data (Execute Before Market Starts)",
                        action="store_true")
    parser.add_argument("-fu", "--force_update",
                        help="Force Update All Data Up to Max. Allowed Years (USE WITH CAUTION)", action="store_true")
    parser.add_argument("-d", "--database", help="Store All CSV Data to Database", action="store_true")

    # Retrieve file names for all strategies as the argument option
    strategy_list = [file_name.split("\\")[1][:-3] for file_name in glob.glob(f"./strategies/*.py") if
                     "__init__" not in file_name and "Strategies" not in file_name]
    parser.add_argument("-s", "--strategy", type=str, choices=strategy_list,
                        help="Execute HFT using Pre-defined Strategy")

    # Evaluate Arguments
    args = parser.parse_args()

    # Initialization Connection
    futu_trade = trading_engine.FutuTrade()

    print(args.force_update)
    if args.update:
        # Daily Update Data
        daily_update_data(futu_trade=futu_trade, force_update=args.force_update)
    if args.database:
        # Update ALl Data to Database
        futu_trade.store_all_data_database()
    if args.strategy:
        # Initialize Strategies
        stock_list = ["HK.00001", "HK.00002", "HK.00003", "HK.00005", "HK.00006", "HK.00011", "HK.00012", "HK.00016",
                      "HK.00017", "HK.00027", "HK.00066", "HK.00101", "HK.00175", "HK.00267", "HK.00288", "HK.00386",
                      "HK.00388", "HK.00669", "HK.00688", "HK.00700", "HK.00762", "HK.00823", "HK.00857", "HK.00883",
                      "HK.00939", "HK.00941", "HK.01038", "HK.01044", "HK.01093", "HK.01109", "HK.01113", "HK.01177",
                      "HK.01299", "HK.01398", "HK.01810", "HK.01876", "HK.01928", "HK.01997", "HK.02007", "HK.02018",
                      "HK.02020", "HK.02269", "HK.02313", "HK.02318", "HK.02319", "HK.02382", "HK.02388", "HK.02628",
                      "HK.03328", "HK.03690", "HK.03988", "HK.09988"]
        init_day_trading(futu_trade, stock_list, args.strategy)

    futu_trade.display_quota()


if __name__ == '__main__':
    main()
