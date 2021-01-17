#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import logger
from data_engine import HKEXInterface, YahooFinanceInterface
from filters import Filters


class StockFilter:
    def __init__(self, stock_filter: Filters):
        self.full_equity_list = HKEXInterface.get_equity_list_full()
        self.stock_filter = stock_filter
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
            yf_data = YahooFinanceInterface.get_stock_history(equity)
            yf_data.columns = [item.lower().strip() for item in yf_data]
            if self.stock_filter.validate(yf_data):
                filtered_stock_list.append(equity)
                self.default_logger.info(
                    f"{equity} is selected based on stock filter {type(self.stock_filter).__name__}")
        return filtered_stock_list
