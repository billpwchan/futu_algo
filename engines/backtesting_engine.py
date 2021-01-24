#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
from datetime import date

import pandas as pd

from strategies.Strategies import Strategies


class Backtesting:
    def __init__(self, stock_list: list, strategy: Strategies, start_date: date, end_date: date):
        self.INITIAL_CAPITAL = 10 ** 6
        self.stock_list = stock_list
        self.strategy = strategy
        self.start_date = start_date
        self.end_date = end_date

    def __prepare_input_data(self):
        for stock_code in self.stock_list:
            delta = 0
            # Check if the file already exists or the dataframe has no data (Non-Trading Day)
            while \
                    not Path(
                        f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv').exists() or pd.read_csv(
                        f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv').empty:
                delta += 1

            self.complete_data = pd.read_csv('./test/test_data/test_data.csv', index_col=None)
            self.input_data = self.complete_data.iloc[:150, :]
            self.test_data = self.complete_data.iloc[150:, :]

    def calculate_return(self):
        print("Hello")
