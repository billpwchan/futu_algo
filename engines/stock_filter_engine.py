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
import logging
import multiprocessing
from datetime import date
from multiprocessing import Pool, cpu_count

import pandas as pd
from tqdm import tqdm

from engines.data_engine import HKEXInterface, TuShareInterface, YahooFinanceInterface
from util import logger
from util.global_vars import *


class StockFilter:
    def __init__(self, stock_filters: list, full_equity_list: list):
        self.default_logger = logger.get_logger("stock_filter")
        self.config = config
        self.full_equity_list = full_equity_list
        self.stock_filters = stock_filters
        self.default_logger.info(f'Stock Filter initialized ({len(full_equity_list)}: {full_equity_list}')

    def validate_stock(self, equity_code):
        try:
            if 'HK' in equity_code:
                quant_data = YahooFinanceInterface.get_stock_history(equity_code)
            elif 'SZ' in equity_code or 'SH' in equity_code:
                quant_data = TuShareInterface.get_stock_history(equity_code)
            else:
                quant_data = pd.DataFrame()
        except Exception as e:
            # self.default_logger.error(f'Exception Happened: {e}')
            return None
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
        except Exception as e:
            self.default_logger.error(f'Exception Happened: {e}')
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
        filtered_stock_list = []
        if 'HK' in self.full_equity_list[0]:
            pool = Pool(min(len(self.full_equity_list), cpu_count()))
            filtered_stock_list = pool.map(self.validate_stock, self.full_equity_list)
            pool.close()
            pool.join()
        else:
            for stock_code in tqdm(self.full_equity_list):
                result = self.validate_stock(stock_code)
                if result is not None:
                    filtered_stock_list.append(result)
        filtered_stock_list = [item for item in filtered_stock_list if item is not None]
        self.default_logger.info(f'Filtered Stock List: {filtered_stock_list}')

        return filtered_stock_list

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

        filtered_stock_df = pd.DataFrame([], columns=['filter', 'code'])

        # Flatten Nested List
        for sublist in filtered_stock_list:
            for record in sublist:
                filtered_stock_df.append({'filter': record[0], 'code': record[1]})
                self.default_logger.info(f"Added Filtered Stock {record[1]} based on Filter {record[0]}")
        filtered_stock_df.to_csv(PATH_FILTER_REPORT / f'{date.today().strftime("%Y-%m-%d")}_stock_list.csv',
                                 index=False, encoding='utf-8-sig')
