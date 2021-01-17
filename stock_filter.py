#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import logger
from data_engine import HKEXInterface, YahooFinanceInterface


class StockFilter:
    def __init__(self, stock_filters: list):
        self.full_equity_list = HKEXInterface.get_equity_list_full()
        self.stock_filters = stock_filters
        self.default_logger = logger.get_logger("stock_filter")

    def get_filtered_equity_pools(self) -> list:
        """
            Use User-Defined Filters to filter bad equities away.
            Based on history data extracted from Yahoo Finance
        :return: Filtered Stock Code List in Futu Stock Code Format
        """
        # stock_history = YahooFinanceInterface.get_stocks_history(self.full_equity_list)
        filtered_stock_list = []

        for equity in self.full_equity_list:
            quant_data = YahooFinanceInterface.get_stock_history(equity)
            quant_data.columns = [item.lower().strip() for item in quant_data]
            info_data = YahooFinanceInterface.get_stock_info(equity)
            if all([stock_filter.validate(quant_data, info_data) for stock_filter in self.stock_filters]):
                filtered_stock_list.append(equity)
                self.default_logger.info(
                    f"{equity} is selected based on stock filter {[type(stock_filter).__name__ for stock_filter in self.stock_filters]}")
        return filtered_stock_list
