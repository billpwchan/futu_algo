#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
import configparser
import json
from datetime import date, timedelta, datetime
from pathlib import Path

import pandas as pd

from engines.data_engine import HKEXInterface
from strategies.Strategies import Strategies
from util import logger


class Backtesting:
    def __init__(self, stock_list: list, start_date: date, end_date: date, observation: int = 100):
        # Program-Related
        self.config = configparser.ConfigParser()
        self.config.read("config.ini")
        self.default_logger = logger.get_logger("backtesting")

        # Backtesting-Related
        self.INITIAL_CAPITAL = 10 ** 6
        self.stock_list = stock_list
        self.strategy = None
        self.start_date = start_date
        self.end_date = end_date
        self.date_range = pd.date_range(self.start_date, self.end_date - timedelta(days=1), freq='d').strftime(
            "%Y-%m-%d").tolist()
        self.observation = observation

        # Transactions-Related
        self.input_data = None
        self.positions = {}
        self.board_lot_mapping = HKEXInterface.get_board_lot_full()
        self.returns_df = pd.DataFrame(columns=self.stock_list, index=self.date_range)
        self.fixed_charge = self.config['Backtesting.Commission.HK'].getfloat('Fixed_Charge')
        self.perc_charge = self.config['Backtesting.Commission.HK'].getfloat('Perc_Charge')

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
            input_df[['open', 'close', 'high', 'low']] = input_df[['open', 'close', 'high', 'low']].apply(pd.to_numeric)
            output_dict[stock_code] = output_dict.get(stock_code, input_df)
            self.default_logger.info(f'{stock_code} 1M Data from Data Files has been processed.')
        self.input_data = output_dict

    def get_backtesting_init_data(self) -> dict:
        return {key: value.copy().iloc[:min(value.shape[0], self.observation)] for (key, value) in
                self.input_data.items()}

    def init_strategy(self, strategy: Strategies):
        self.strategy = strategy

    def calculate_return(self):
        backtesting_data = {key: value.iloc[self.observation:].reset_index(drop=True) for (key, value) in
                            self.input_data.items()}
        for stock_code in self.stock_list:
            for index, row in backtesting_data[stock_code].iterrows():
                latest_data = row.to_frame().transpose()
                latest_data.reset_index(drop=True, inplace=True)
                self.strategy.parse_data(latest_data=latest_data)
                if self.strategy.buy(stock_code):
                    if self.positions.get(stock_code, 0) == 0:
                        self.default_logger.info(f"SIMULATE BUY ORDER for {stock_code} using PRICE {row['close']}")
                        self.positions[stock_code] = self.positions.get(stock_code, row['close'])
                    elif self.positions.get(stock_code, 0) != 0:
                        self.default_logger.info(
                            f"BUY ORDER CANCELLED for {stock_code} because existing holding positions")
                if self.strategy.sell(stock_code):
                    if self.positions.get(stock_code, 0) != 0:
                        current_price = row['close']
                        buy_price = self.positions.get(stock_code, current_price)
                        qty = self.board_lot_mapping.get(stock_code, 0)
                        EBIT = (current_price - buy_price) * qty
                        profit = EBIT * self.perc_charge - self.fixed_charge
                        current_date = datetime.strptime(row['time_key'], '%Y-%m-%d  %H:%M:%S').date()

                        self.returns_df.loc[str(current_date), stock_code] += profit

                        self.default_logger.info(f"SIMULATE SELL ORDER FOR {stock_code} using PRICE {row['close']}")
                        self.default_logger.info(f"PROFIT earned: {profit}")
                        # Update Positions
                        self.positions[stock_code] = 0

        self.returns_df.to_csv('output.csv')
