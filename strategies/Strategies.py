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


import time
from abc import ABC, abstractmethod

import pandas as pd


class Strategies(ABC):
    def __init__(self, input_data: dict):
        self.input_data = input_data
        super().__init__()

    @abstractmethod
    def parse_data(self, stock_list: list, latest_data: pd.DataFrame, backtesting: bool):
        """
        Stock List for Retrieval Mode
        Latest Data for Subscription Mode
        Backtesting for Backtesting Mode
        :param stock_list:
        :param latest_data:
        :param backtesting:
        """
        pass

    @abstractmethod
    def buy(self, stock_code) -> bool:
        pass

    @abstractmethod
    def sell(self, stock_code) -> bool:
        pass

    def get_input_data(self) -> dict:
        return self.input_data.copy()

    def get_input_data_stock_code(self, stock_code: str) -> pd.DataFrame:
        return self.input_data[stock_code].copy()

    def set_input_data(self, input_data: dict) -> None:
        self.input_data = input_data.copy()

    def set_input_data_stock_code(self, stock_code: str, input_df: pd.DataFrame) -> None:
        self.input_data[stock_code] = input_df.copy()


def timeit(method):
    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()
        if 'log_time' in kw:
            name = kw.get('log_name', method.__name__.upper())
            kw['log_time'][name] = int((te - ts) * 1000)
        else:
            print('%r  %2.2f ms' % (method.__name__, (te - ts) * 1000))
        return result

    return timed
