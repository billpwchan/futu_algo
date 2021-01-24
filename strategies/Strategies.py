#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import time
from abc import ABC, abstractmethod

import pandas as pd


class Strategies(ABC):
    def __init__(self, input_data: dict):
        self.input_data = input_data
        super().__init__()

    @abstractmethod
    def parse_data(self, latest_data: pd.DataFrame, backtesting: bool):
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
