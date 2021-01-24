#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
import configparser
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from strategies.Strategies import Strategies
from util import logger


class Backtesting:
    def __init__(self, stock_list: list, start_date: date, end_date: date):
        self.INITIAL_CAPITAL = 10 ** 6
        self.stock_list = stock_list
        self.strategy = None
        self.start_date = start_date
        self.end_date = end_date
        self.date_range = pd.date_range(self.start_date, self.end_date - timedelta(days=1), freq='d').strftime(
            "%Y-%m-%d").tolist()
        self.input_data = None
        self.config = configparser.ConfigParser()
        self.config.read("config.ini")
        self.default_logger = logger.get_logger("backtesting")

    def prepare_input_data_file_1M(self) -> None:
        column_names = json.loads(self.config.get('FutuOpenD.DataFormat', 'HistoryDataFormat'))
        output_dict = {}
        for stock_code in self.stock_list:
            # input_df refers to the all the 1M data from start_date to end_date in pd.Dataframe format
            input_df = pd.concat(
                [pd.read_csv(f'./data/{stock_code}/{stock_code}_{input_date}_1M.csv', index_col=None) for input_date in
                 self.date_range if
                 Path(f'./data/{stock_code}/{stock_code}_{input_date}_1M.csv').exists() and (not pd.read_csv(
                     f'./data/{stock_code}/{stock_code}_{input_date}_1M.csv').empty)],
                ignore_index=True)

            output_dict[stock_code] = output_dict.get(stock_code, input_df)
            self.default_logger.info(f'{stock_code} 1M Data from Data Files has been processed.')
        self.input_data = output_dict

    def get_backtesting_init_data(self, observation: int = 100) -> dict:
        return {key: value.copy().iloc[:min(value.shape[0], observation)] for (key, value) in self.input_data.items()}

    def init_strategy(self, strategy: Strategies):
        print("Hello")

    def calculate_return(self):
        print("Hello")
