#  Futu Algo: Algorithmic High-Frequency Trading Framework
# 
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
# 
#      http://www.apache.org/licenses/LICENSE-2.0
# 
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# 
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
#  Copyright (c)  billpwchan - All Rights Reserved


import argparse
import importlib
from multiprocessing import Process

import yaml

from engines import *
from strategies.Strategies import Strategies
from util.global_vars import *


def __daily_update_filters():
    filters = list(__init_filter(filter_list=['all']))
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
        futu_trade.update_1M_data(stock_code, force_update=force_update, default_days=80)

    # Daily Update FuTu Historical Data
    # futu_trade.store_all_data_database()

    # Clean non-trading days data
    DataProcessingInterface.clear_empty_data()

    for proc in procs:
        proc.join()


def __dynamic_instantiation(prefix: str, module_name: str, optional_parameter=None):
    filter_module = importlib.import_module(f"{prefix}.{module_name}")
    # Assume the class name is identical with the file name except for the underscore _
    class_ = getattr(filter_module, module_name.replace("_", ""))
    if optional_parameter is not None:
        return class_(optional_parameter)
    else:
        return class_()


def __init_strategy(strategy_name: str, input_data: dict) -> Strategies:
    """
    Return a trading strategy instance using a strategy name in string.
    :param strategy_name: an available strategy module name in the strategies folder
    :param input_data: Initialized input data for the strategy to calculate the technical indicator
    :return: a strategy instance
    """
    return __dynamic_instantiation(prefix="strategies", module_name=strategy_name, optional_parameter=input_data.copy())


def __init_filter(filter_list: list) -> list:
    """
    Return a list of filters instances using a list of filter names.
    If 'all' is specified, all available filters will be returned
    :param filter_list: a list of filter names (in strings)
    :return: a list of filters
    """
    if "all" in filter_list:
        filter_list = [Path(file_name).name[:-3] for file_name in glob.glob("./filters/*.py") if
                       "__init__" not in file_name and "Filters" not in file_name]

    return [__dynamic_instantiation(prefix="filters", module_name=filter_name) for filter_name in filter_list]


def init_backtesting(strategy_name: str):
    start_date = datetime(2019, 3, 20).date()
    end_date = datetime(2021, 3, 23).date()
    stock_list = data_engine.YahooFinanceInterface.get_top_30_hsi_constituents()
    bt = Backtesting(stock_list=stock_list, start_date=start_date, end_date=end_date, observation=100)
    bt.prepare_input_data_file_custom_M(custom_interval=5)
    # bt.prepare_input_data_file_1M()
    strategy = __dynamic_instantiation(prefix="strategies", module_name=strategy_name,
                                       optional_parameter=bt.get_backtesting_init_data())
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
    filters = __init_filter(filter_list)
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
    strategy_list = [Path(file_name).name[:-3] for file_name in glob.glob("./strategies/*.py") if
                     "__init__" not in file_name and "Strategies" not in file_name]
    parser.add_argument("-s", "--strategy", type=str, choices=strategy_list,
                        help="Execute HFT using Pre-defined Strategy")

    parser.add_argument("-b", "--backtesting", type=str, choices=strategy_list,
                        help="Backtesting a Pre-defined Strategy")

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
        init_backtesting(args.backtesting)

    futu_trade.display_quota()


if __name__ == '__main__':
    main()
