#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import argparse
import glob
from datetime import datetime

from futu import KLType

from engines import trading_engine, data_engine
from engines.backtesting_engine import Backtesting
from engines.stock_filter_engine import StockFilter
from filters.Boll_Gold_Cross import BollGoldCross
from filters.Boll_Up import BollUp
from filters.DZX_1B import DZX1B
from filters.Filters import Filters
from filters.MA_Simple import MASimple
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


def daily_update_data(futu_trade, force_update: bool = False):
    # Daily Update Filtered Security
    filters = list(__init_filter(filter_name='all'))
    stock_filter = StockFilter(stock_filters=filters)
    stock_filter.update_filtered_equity_pools()

    # Daily Update Stock Info (Need to Rethink!!!)
    # stock_filter.update_stock_info()

    # Daily Update HKEX Security List & Subscribed Data
    data_engine.HKEXInterface.update_security_list_full()
    stock_list = data_engine.DatabaseInterface(database_path='./database/stock_data.sqlite').get_stock_list()
    for stock_code in stock_list:
        futu_trade.update_DW_data(stock_code, force_update=force_update, k_type=KLType.K_DAY)
        futu_trade.update_DW_data(stock_code, force_update=force_update, k_type=KLType.K_WEEK)
        futu_trade.update_1M_data(stock_code, force_update=force_update)


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
    start_date = datetime(2020, 1, 1).date()
    end_date = datetime(2020, 2, 3).date()
    bt = Backtesting(stock_list=['HK.00001'], start_date=start_date,
                     end_date=end_date)
    bt.prepare_input_data_file_1M()
    strategy = KDJMACDClose(input_data=bt.get_backtesting_init_data())
    bt.init_strategy(strategy)
    bt.calculate_return()


def init_day_trading(futu_trade: trading_engine.FutuTrade, stock_list: list, strategy_name: str):
    input_data = futu_trade.get_data_realtime(stock_list, sub_type=KLType.K_1M, kline_num=100)
    strategy = __init_strategy(strategy_name=strategy_name, input_data=input_data)
    futu_trade.cur_kline_subscription(input_data, stock_list=stock_list, strategy=strategy, timeout=3600 * 12)


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

    # Retrieve file names for all strategies as the argument option
    strategy_list = [file_name.split("\\")[1][:-3] for file_name in glob.glob(f"./strategies/*.py") if
                     "__init__" not in file_name and "Strategies" not in file_name]
    parser.add_argument("-s", "--strategy", type=str, choices=strategy_list,
                        help="Execute HFT using Pre-defined Strategy")

    # Retrieve file names for all strategies as the argument option
    filter_list = [file_name.split("\\")[1][:-3] for file_name in glob.glob(f"./filters/*.py") if
                   "__init__" not in file_name and "Filters" not in file_name]
    parser.add_argument("-f", "--filter", type=str, choices=filter_list, nargs="+",
                        help="Filter Stock List based on Pre-defined Filters")

    # Evaluate Arguments
    args = parser.parse_args()

    # Initialization Connection
    futu_trade = trading_engine.FutuTrade()

    if args.update:
        # Daily Update Data
        daily_update_data(futu_trade=futu_trade, force_update=args.force_update)
    if args.database:
        # Update ALl Data to Database
        futu_trade.store_all_data_database()
    if args.filter:
        filtered_stock_list = init_stock_filter(args.filter)
        print(filtered_stock_list)
    if args.strategy:
        # Initialize Strategies
        # stock_list = filtered_stock_list if args.filter else data_engine.DatabaseInterface(
        #     database_path='./database/stock_data.sqlite').get_stock_list()
        stock_list = ['HK.00322', 'HK.01208', 'HK.01378', 'HK.01530', 'HK.01860', 'HK.02600']
        stock_list.extend(data_engine.YahooFinanceInterface.get_top_30_hsi_constituents())
        init_day_trading(futu_trade, stock_list, args.strategy)

    init_backtesting()

    futu_trade.display_quota()


if __name__ == '__main__':
    main()
