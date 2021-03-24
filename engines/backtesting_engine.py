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
import pyfolio as pf

from engines.data_engine import HKEXInterface, DataProcessingInterface
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
        self.capital = self.INITIAL_CAPITAL
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
        self.transactions = pd.DataFrame(columns=['time_key', 'code', 'price', 'quantity', 'trd_side'])
        self.board_lot_mapping = HKEXInterface.get_board_lot_full()
        self.returns_df = pd.DataFrame(0, columns=self.stock_list, index=self.date_range)
        self.returns_df = self.returns_df.apply(pd.to_numeric)
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

    def prepare_input_data_file_custom_M(self, custom_interval: int = 5) -> None:
        column_names = json.loads(self.config.get('FutuOpenD.DataFormat', 'HistoryDataFormat'))
        output_dict = {}
        for input_date in self.date_range:
            custom_dict = DataProcessingInterface.get_custom_interval_data(target_date=input_date,
                                                                           custom_interval=custom_interval,
                                                                           stock_list=self.stock_list)
            for stock_code, df in custom_dict.items():
                output_dict[stock_code] = pd.concat(
                    [output_dict.get(stock_code, pd.DataFrame(columns=column_names)), df],
                    ignore_index=True)
        for stock_code, df in output_dict.items():
            df[['open', 'close', 'high', 'low']] = df[['open', 'close', 'high', 'low']].apply(pd.to_numeric)
        self.input_data = output_dict

    def get_backtesting_init_data(self) -> dict:
        return {key: value.copy().iloc[:min(value.shape[0], self.observation)] for (key, value) in
                self.input_data.items()}

    def init_strategy(self, strategy: Strategies):
        self.strategy = strategy

    def calculate_return(self):
        # We want to get the calculated technical indicators values (e.g., MACD, KDJ, etc.) for all records
        ta_backtesting_data = {}
        for stock_code in self.stock_list:
            self.strategy.parse_data(latest_data=self.input_data[stock_code], backtesting=True)
            ta_backtesting_data[stock_code] = self.strategy.get_input_data_stock_code(stock_code)

        # Revert back to its initial state (i.e., with 0-99 beginning records)
        self.strategy.set_input_data(self.get_backtesting_init_data())

        # ASSUME All Dataframe has the same shape (Should Be Validated in Prepare Data Step)
        # Start from the 100 records (i.e., defined as self.observation)
        for index in range(self.observation, list(ta_backtesting_data.values())[0].shape[0]):
            # For each new timestamp, check for each stock if they satisfy the buy/sell condition
            for stock_code in self.stock_list:
                # if backtesting_data[stock_code].shape[0] <= index:
                #     self.default_logger.error(f"INVALID DIMENSION FOUND IN BACKTESTING ENGINE FOR {stock_code}")
                #     continue

                # Overwrite input data in the strategy
                start_index = index - self.observation
                end_index = index
                input_df = ta_backtesting_data[stock_code].iloc[start_index:end_index]
                self.strategy.set_input_data_stock_code(stock_code=stock_code, input_df=input_df)

                row = input_df.iloc[-1]

                if self.strategy.buy(stock_code):
                    if self.positions.get(stock_code, 0) == 0 and self.capital >= 0:
                        self.positions[stock_code] = self.positions.get(stock_code, row['close'])
                        current_price = row['close']
                        qty = self.board_lot_mapping.get(stock_code, 0)
                        # Update Holding Capital
                        self.capital -= current_price * qty
                        # Update Transaction History Dataframe
                        self.transactions = self.transactions.append(
                            pd.Series([row['time_key'], stock_code, current_price, qty, 'BUY'],
                                      index=self.transactions.columns), ignore_index=True)
                        self.default_logger.info(f"SIMULATE BUY ORDER for {stock_code} using PRICE {row['close']}")
                    elif self.positions.get(stock_code, 0) != 0:
                        self.default_logger.info(
                            f"BUY ORDER CANCELLED for {stock_code} because existing holding positions")
                if self.strategy.sell(stock_code):
                    if self.positions.get(stock_code, 0) != 0:
                        current_price = row['close']
                        buy_price = self.positions[stock_code]
                        qty = self.board_lot_mapping.get(stock_code, 0)
                        EBIT = (current_price - buy_price) * qty

                        # Profit = EBIT - fixed charge (15 HKD * 2) - Percentage Charge (Buy Value + Sale Value) * 0.10%
                        profit = EBIT - 2 * self.fixed_charge - (
                                buy_price + current_price) * qty * self.perc_charge / 100
                        current_date = datetime.strptime(row['time_key'], '%Y-%m-%d  %H:%M:%S').date()

                        self.returns_df.loc[str(current_date), stock_code] += profit
                        self.capital += current_price * qty
                        self.transactions = self.transactions.append(
                            pd.Series([row['time_key'], stock_code, current_price, qty, 'SELL'],
                                      index=self.transactions.columns), ignore_index=True)
                        self.default_logger.info(f"SIMULATE SELL ORDER FOR {stock_code} using PRICE {row['close']}")
                        self.default_logger.info(f"PROFIT earned: {profit}")
                        # Update Positions
                        self.positions.pop(stock_code, None)
        self.returns_df['returns'] = self.returns_df.sum(axis=1)
        time_key = datetime.now().strftime("%Y_%m_%d-%I_%M_%S_%p")
        self.returns_df.to_csv(f'./backtesting_report/{time_key}_Returns.csv')
        self.transactions.to_csv(f'./backtesting_report/{time_key}_Transactions.csv')

    def create_tear_sheet(self):
        return_ser = pd.read_csv('output.csv', index_col=0, header=0)
        return_ser.index = pd.to_datetime(return_ser.index)
        # pf.create_returns_tear_sheet(return_ser['HK.00001'])
        with open("data.html", "w") as file:
            file.write(pf.create_simple_tear_sheet(returns=return_ser['HK.00001']))
