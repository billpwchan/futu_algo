#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
import configparser
import json
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
        try:
            quant_data = YahooFinanceInterface.get_stock_history(equity_code)
        except:
            self.default_logger.error('Exception Happened')
        quant_data.columns = [item.lower().strip() for item in quant_data]
        # info_data = YahooFinanceInterface.get_stock_info(equity_code)
        info_data = {}
        if all([stock_filter.validate(quant_data, info_data) for stock_filter in self.stock_filters]):
            self.default_logger.info(
                f"{equity_code} is selected based on stock filter {[type(stock_filter).__name__ for stock_filter in self.stock_filters]}")
            return equity_code
        return None

    def validate_stock_individual(self, equity_code):
        try:
            quant_data = YahooFinanceInterface.get_stock_history(equity_code)
        except:
            self.default_logger.error('Exception Happened')
        quant_data.columns = [item.lower().strip() for item in quant_data]
        # info_data = YahooFinanceInterface.get_stock_info(equity_code)
        info_data = {}
        output_list = []
        for stock_filter in self.stock_filters:
            if stock_filter.validate(quant_data, info_data):
                self.default_logger.info(
                    f"{equity_code} is selected based on stock filter {type(stock_filter).__name__}")
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
        pool.close()
        pool.join()

        return [item for item in filtered_stock_list if item is not None]

    def update_filtered_equity_pools(self):
        """
           Use User-Defined Filters to filter bad equities away.
           Based on history data extracted from Yahoo Finance
       :return: Filtered Stock Code List in Futu Stock Code Format
       """
        pool = Pool(cpu_count())
        filtered_stock_list = pool.map(self.validate_stock_individual, self.full_equity_list)
        pool.close()
        pool.join()
        # filtered_stock_list = []
        # for stock_code in self.full_equity_list:
        #     filtered_stock_list.append(self.validate_stock_individual(stock_code))

        # Remove Redundant Records (If Exists)
        database = data_engine.DatabaseInterface(database_path=self.config['Database'].get('Database_path'))
        database.delete_stock_pool_from_date(date.today().strftime("%Y-%m-%d"))
        database.commit()
        # Flatten Nested List
        for sublist in filtered_stock_list:
            for record in sublist:
                database.add_stock_pool(date.today().strftime("%Y-%m-%d"), record[0], record[1])
                self.default_logger.info(f"Added Filtered Stock {record[1]} based on Filter {record[0]}")
            database.commit()

    def parse_stock_info(self, stock_code):
        return (stock_code, YahooFinanceInterface.get_stock_info(stock_code))

    def update_stock_info(self):
        pool = Pool(cpu_count())
        output_list = pool.map(self.parse_stock_info, self.full_equity_list)
        pool.close()
        pool.join()

        output_dict = {}
        for record in output_list:
            output_dict[record[0]] = output_dict.get(record[0], record[1])
            self.default_logger.info(f"Updated Stock Info for {record[0]}")

        with open('./data/Stock_Pool/stock_info.json', 'w') as fp:
            json.dump(output_dict, fp)
