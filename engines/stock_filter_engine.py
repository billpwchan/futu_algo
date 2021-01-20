#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
import configparser
from datetime import date
from multiprocessing import Pool, cpu_count

from engines import data_engine
from engines.data_engine import HKEXInterface, YahooFinanceInterface
from util import logger


class StockFilter:
    def __init__(self, stock_filters: list):
        self.default_logger = logger.get_logger("stock_filter")
        self.config = configparser.ConfigParser()
        self.config.read("config.ini")
        self.full_equity_list = HKEXInterface.get_equity_list_full()
        self.stock_filters = stock_filters

    def validate_stock(self, equity_code):
        quant_data = YahooFinanceInterface.get_stock_history(equity_code)
        quant_data.columns = [item.lower().strip() for item in quant_data]
        # info_data = YahooFinanceInterface.get_stock_info(equity_code)
        info_data = {}
        if all([stock_filter.validate(quant_data, info_data) for stock_filter in self.stock_filters]):
            self.default_logger.info(
                f"{equity_code} is selected based on stock filter {[type(stock_filter).__name__ for stock_filter in self.stock_filters]}")
            return equity_code
        return None

    def validate_stock_individual(self, equity_code):
        quant_data = YahooFinanceInterface.get_stock_history(equity_code)
        quant_data.columns = [item.lower().strip() for item in quant_data]
        # info_data = YahooFinanceInterface.get_stock_info(equity_code)
        info_data = {}
        output_list = []
        for stock_filter in self.stock_filters:
            if stock_filter.validate(quant_data, info_data):
                self.default_logger.info(
                    f"{equity_code} is selected based on stock filter {[type(stock_filter).__name__ for stock_filter in self.stock_filters]}")
                output_list.append((type(stock_filter).__name__, equity_code))
        return output_list

    def get_filtered_equity_pools(self) -> list:
        """
            Use User-Defined Filters to filter bad equities away.
            Based on history data extracted from Yahoo Finance
        :return: Filtered Stock Code List in Futu Stock Code Format
        """
        # database = data_engine.DatabaseInterface(database_path=self.config['Database'].get('Database_path'))

        pool = Pool(cpu_count())
        filtered_stock_list = pool.map(self.validate_stock, self.full_equity_list)

        return [item for item in filtered_stock_list if item is not None]

    def update_filtered_equity_pools(self):
        """
           Use User-Defined Filters to filter bad equities away.
           Based on history data extracted from Yahoo Finance
       :return: Filtered Stock Code List in Futu Stock Code Format
       """
        pool = Pool(cpu_count())
        filtered_stock_list = pool.map(self.validate_stock_individual, self.full_equity_list)

        # Remove Redundant Records (If Exists)
        database = data_engine.DatabaseInterface(database_path=self.config['Database'].get('Database_path'))
        database.delete_stock_pool_from_date(date.today().strftime("%Y-%m-%d"))
        database.commit()

        # Flatten Nested List
        for sublist in filtered_stock_list:
            for record in sublist:
                database.add_stock_pool(date.today().strftime("%Y-%m-%d"), record[0], record[1],
                                        YahooFinanceInterface.get_stock_info(record[0])['longName'])
        database.commit()
