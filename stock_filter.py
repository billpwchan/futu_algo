#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

from data_engine import HKEXInterface, YahooFinanceInterface
from filters import Filters


class StockFilter:
    def __init__(self, stock_filter: Filters):
        self.full_equity_list = HKEXInterface.get_equity_list_full()
        self.stock_filter = stock_filter

    def get_filtered_equity_pools(self) -> list:
        """
            Use User-Defined Filters to filter bad equities away.
            Based on history data extracted from Yahoo Finance
        :return: Filtered Stock Code List in Futu Stock Code Format
        """
        return [equity for equity in self.full_equity_list if
                self.stock_filter.validate(YahooFinanceInterface.get_stocks_history(equity))]
