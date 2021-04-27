#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import argparse
import configparser
import glob
import json
import os
from datetime import datetime
from multiprocessing import Process
from pathlib import Path

import yaml
from futu import KLType, SubType

from engines import trading_engine, data_engine, email_engine
from engines.backtesting_engine import Backtesting
from engines.data_engine import YahooFinanceInterface, DataProcessingInterface
from engines.stock_filter_engine import StockFilter
from filters.Boll_Gold_Cross import BollGoldCross
from filters.Boll_Up import BollUp
from filters.DZX_1B import DZX1B
from filters.Filters import Filters
from filters.MA_Simple import MASimple
from filters.MA_Up_Trend import MAUpTrend
from filters.Price_Threshold import PriceThreshold
from filters.Quant_Breakthrough import QuantBreakthrough
from filters.Triple_Cross import TripleCross
from filters.Volume_Threshold import VolumeThreshold
from strategies.EMA_Ribbon import EMARibbon
from strategies.KDJ_Cross import KDJCross
from strategies.KDJ_MACD_Close import KDJMACDClose
from strategies.MACD_Cross import MACDCross
from strategies.Quant_Legendary import QuantLegendary
from strategies.RSI_Threshold import RSIThreshold
from strategies.Short_Term_Band import ShortTermBand
from strategies.Strategies import Strategies


def __daily_update_filters():
    filters = list(__init_filter(filter_name='all'))
    stock_filter = StockFilter(stock_filters=filters)
    stock_filter.update_filtered_equity_pools()


def daily_update_data(futu_trade, stock_list: list, force_update: bool = False):
    # Daily Update Filtered Security
    procs = []
    proc = Process(target=__daily_update_filters)  # instantiating without any argument
    procs.append(proc)
    proc.start()

    # Daily Update Stock Info (Need to Rethink!!!)
    # stock_filter.update_stock_info()

    # Daily Update HKEX Security List & Subscribed Data
    data_engine.HKEXInterface.update_security_list_full()

    # Daily Update Owner Plate for all Stocks
    full_equity_list = data_engine.HKEXInterface.get_equity_list_full()
    futu_trade.update_owner_plate(stock_list=full_equity_list)

    # Update basic information for all markets
    futu_trade.update_stock_basicinfo()

    # Update historical k-line
    for stock_code in stock_list:
        futu_trade.update_DW_data(stock_code, force_update=force_update, k_type=KLType.K_DAY)
        futu_trade.update_DW_data(stock_code, force_update=force_update, k_type=KLType.K_WEEK)
        futu_trade.update_1M_data(stock_code, force_update=force_update)

    # Daily Update FuTu Historical Data
    # futu_trade.store_all_data_database()

    # Clean non-trading days data
    DataProcessingInterface.clear_empty_data()

    for proc in procs:
        proc.join()


def __init_strategy(strategy_name: str, input_data: dict) -> Strategies:
    strategies = {
        'EMA_Ribbon': EMARibbon(input_data=input_data.copy()),
        'KDJ_Cross': KDJCross(input_data=input_data.copy()),
        'KDJ_MACD_Close': KDJMACDClose(input_data=input_data.copy()),
        'MACD_Cross': MACDCross(input_data=input_data.copy()),
        'RSI_Threshold': RSIThreshold(input_data=input_data.copy()),
        'Short_Term_Band': ShortTermBand(input_data=input_data.copy()),
        'Quant_Legendary': QuantLegendary(input_data=input_data.copy())
    }
    # Default return simplest MACD Cross Strategy
    return strategies.get(strategy_name, MACDCross(input_data=input_data))


def __init_filter(filter_name: str) -> Filters or dict:
    filters = {
        'Boll_Gold_Cross': BollGoldCross(),
        'Boll_Up': BollUp(),
        'DZX_1B': DZX1B(),
        'MA_Simple': MASimple(),
        'MA_Up_Trend': MAUpTrend(),
        'Price_Threshold': PriceThreshold(price_threshold=1),
        'Volume_Threshold': VolumeThreshold(volume_threshold=10 ** 7),
        'Triple_Cross': TripleCross(),
        'Quant_Breakthrough': QuantBreakthrough()
    }
    # Default return simplest MA Stock Filter
    if filter_name == 'all':
        return filters.values()
    return filters.get(filter_name, MASimple())


def init_backtesting():
    start_date = datetime(2019, 3, 20).date()
    end_date = datetime(2021, 3, 23).date()
    stock_list = data_engine.YahooFinanceInterface.get_top_30_hsi_constituents()
    bt = Backtesting(stock_list=stock_list, start_date=start_date, end_date=end_date, observation=100)
    bt.prepare_input_data_file_custom_M(custom_interval=5)
    # bt.prepare_input_data_file_1M()
    strategy = KDJMACDClose(input_data=bt.get_backtesting_init_data(), observation=100)
    bt.init_strategy(strategy)
    bt.calculate_return()
    # bt.create_tear_sheet()


def init_day_trading(futu_trade: trading_engine.FutuTrade, stock_list: list, strategy_name: str,
                     stock_strategy_map: dict,
                     subtype: SubType = SubType.K_5M):
    input_data = futu_trade.get_data_realtime(stock_list, sub_type=subtype, kline_num=100)
    # strategy_map = dict object {'HK.00001', MACD_Cross(), 'HK.00002', MACD_Cross()...}
    strategy_map = {stock_code: __init_strategy(strategy_name=stock_strategy_map.get(stock_code, strategy_name),
                                                input_data=input_data) for stock_code in stock_list}
    futu_trade.cur_kline_subscription(input_data, stock_list=stock_list, strategy_map=strategy_map, timeout=3600 * 12,
                                      subtype=subtype)


def init_stock_filter(filter_list: list) -> list:
    filters = [__init_filter(input_filter) for input_filter in filter_list]
    stock_filter = StockFilter(stock_filters=filters)
    return stock_filter.get_filtered_equity_pools()


def main():
    # Initialize Argument Parser
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--update", help="Daily Update Data (Execute Before Market Starts)",
                        action="store_true")
    parser.add_argument("-fu", "--force_update",
                        help="Force Update All Data Up to Max. Allowed Years (USE WITH CAUTION)", action="store_true")
    parser.add_argument("-d", "--database", help="Store All CSV Data to Database", action="store_true")
    parser.add_argument("-b", "--backtesting", help="Backtesting strategy", action="store_true")

    # Retrieve file names for all strategies as the argument option
    strategy_list = [Path(file_name).name[:-3] for file_name in glob.glob("./strategies/*.py") if
                     "__init__" not in file_name and "Strategies" not in file_name]
    parser.add_argument("-s", "--strategy", type=str, choices=strategy_list,
                        help="Execute HFT using Pre-defined Strategy")

    # Retrieve file names for all strategies as the argument option
    filter_list = [Path(file_name).name[:-3] for file_name in glob.glob("./filters/*.py") if
                   "__init__" not in file_name and "Filters" not in file_name]
    parser.add_argument("-f", "--filter", type=str, choices=filter_list, nargs="+",
                        help="Filter Stock List based on Pre-defined Filters")
    parser.add_argument("-en", "--email_name", type=str, help="Name of the applied stock filtering techniques")

    # Evaluate Arguments
    args = parser.parse_args()

    # Initialization Connection
    futu_trade = trading_engine.FutuTrade()
    email_handler = email_engine.Email()

    # Initialize Config Parser
    config = configparser.ConfigParser()
    config.read("config.ini")

    with open('stock_strategy_map.yml', 'r') as infile:
        stock_strategy_map = yaml.safe_load(infile)

    # Initialize Stock List
    stock_list = json.loads(config.get('TradePreference', 'StockList'))
    if not stock_list:
        # stock_list = data_engine.DatabaseInterface(
        #     database_path=config.get('Database', 'Database_path')).get_stock_list()
        # Directly get list of stock codes from the data folder. Easier.
        stock_list = [str(f.path).replace('./data/', '') for f in os.scandir("./data/") if f.is_dir()]
        stock_list = stock_list[:-1]

    if args.filter:
        filtered_stock_list = init_stock_filter(args.filter)
        filtered_stock_dict = YahooFinanceInterface.get_stocks_email(filtered_stock_list)
        subscription_list = json.loads(config.get('Email', 'SubscriptionList'))
        for subscriber in subscription_list:
            filter_name = args.email_name if args.email_name else "Default Stock Filter"
            email_handler.write_daily_stock_filter_email(subscriber, filter_name, filtered_stock_dict)
    if args.update or args.force_update:
        # Daily Update Data
        daily_update_data(futu_trade=futu_trade, stock_list=stock_list, force_update=args.force_update)
    if args.database:
        # Update ALl Data to Database
        futu_trade.store_all_data_database()
    if args.strategy:
        # Stock Basket => 4 Parts
        # 1. Currently Holding Stocks (i.e., in the trading account with existing position)
        # 2. Filtered Stocks (i.e., based on 1D data if -f option is adopted
        # 3. StockList in config.ini (i.e., if empty, default use all stocks in the database)
        # 4. Top 30 HSI Constituents
        if args.filter:
            stock_list.extend(filtered_stock_list)
        # stock_list.extend(data_engine.YahooFinanceInterface.get_top_30_hsi_constituents())

        init_day_trading(futu_trade, stock_list, args.strategy, stock_strategy_map)
    if args.backtesting:
        init_backtesting()

    futu_trade.display_quota()


if __name__ == '__main__':
    main()
