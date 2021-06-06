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
import json
import warnings
from collections import ChainMap
from datetime import date, datetime, timedelta
from multiprocessing import Pool, cpu_count

import pandas as pd

from engines.data_engine import DataProcessingInterface, HKEXInterface
from strategies.Strategies import Strategies
from util import logger
from util.global_vars import *

warnings.filterwarnings('ignore')


class Backtesting:
    def __init__(self, stock_list: list, start_date: date, end_date: date, observation: int = 100):
        # Program-Related
        self.config = config
        self.default_logger = logger.get_logger("backtesting")

        # Backtesting-Related
        self.INITIAL_CAPITAL = 10 ** 6
        self.capital = self.INITIAL_CAPITAL
        self.lot_size_multiplier = self.config['TradePreference'].getfloat('LotSizeMultiplier')
        self.max_perc_per_asset = self.config['TradePreference'].getfloat('MaxPercPerAsset')
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
        self.fixed_charge = self.config['Backtesting.Commission.HK'].getfloat('FixedCharge')
        self.perc_charge = self.config['Backtesting.Commission.HK'].getfloat('PercCharge')

    def prepare_input_data_file_1M(self) -> None:
        """
        Prepare input data with 1M interval. Directly load data from stored .csv file (Assume 1M data already downloaded)
        """
        self.input_data = DataProcessingInterface.get_1M_data_range(self.date_range, self.stock_list)

    def process_custom_interval_data(self, stock_code, column_names, custom_interval: int = 5):
        output_dict = {}
        for input_date in self.date_range:
            custom_dict = DataProcessingInterface.get_custom_interval_data(target_date=input_date,
                                                                           custom_interval=custom_interval,
                                                                           stock_list=[stock_code])
            for stock_code, df in custom_dict.items():
                output_dict[stock_code] = pd.concat(
                    [output_dict.get(stock_code, pd.DataFrame(columns=column_names)), df],
                    ignore_index=True)

        for stock_code, input_df in output_dict.items():
            input_df[['open', 'close', 'high', 'low']] = input_df[['open', 'close', 'high', 'low']].apply(pd.to_numeric)
            input_df.sort_values(by='time_key', ascending=True, inplace=True)
        return output_dict

    def prepare_input_data_file_custom_M(self, custom_interval: int = 5) -> None:
        """
        Prepare input data with customized interval. Generated based on 1M data.
        Multi-threading enabled
        :param custom_interval: Integer
        """
        column_names = json.loads(self.config.get('FutuOpenD.DataFormat', 'HistoryDataFormat'))

        # Use Starmap to pass multiple arguments into process_custom_interval_data function
        # Received a list of dict in format [{'HK.00001': pd.Dataframe}, {...}]
        pool = Pool(min(cpu_count(), len(self.stock_list)))
        list_of_custom_dict = pool.starmap(self.process_custom_interval_data,
                                           [(stock_code, column_names, custom_interval) for stock_code in
                                            self.stock_list])
        pool.close()
        pool.join()

        output_dict = dict(ChainMap(*list_of_custom_dict))
        self.input_data = output_dict
        self.input_data['HK.01997'].to_csv("STEP 1.csv")

    def get_backtesting_init_data(self) -> dict:
        return {key: value.copy().iloc[:min(value.shape[0], self.observation)] for (key, value) in
                self.input_data.items()}

    def init_strategy(self, strategy: Strategies):
        self.strategy = strategy

    def calculate_return(self):
        # We want to get the calculated technical indicators values (e.g., MACD, KDJ, etc.) for all records
        unique_time = set()
        ta_backtesting_data = {}
        for stock_code in self.stock_list:
            # !!! It's concatenated. So have to reset the entire input_data in the strategy!
            self.strategy.set_input_data_stock_code(stock_code=stock_code,
                                                    input_df=self.strategy.get_input_data_stock_code(
                                                        stock_code=stock_code)[0:0])
            self.strategy.parse_data(latest_data=self.input_data[stock_code], backtesting=True)
            ta_backtesting_data[stock_code] = self.strategy.get_input_data_stock_code(stock_code)
            unique_time.update(ta_backtesting_data[stock_code]['time_key'])
            ta_backtesting_data[stock_code].set_index('time_key', inplace=True, drop=False)
            # Remove duplicated indices
            ta_backtesting_data[stock_code] = ta_backtesting_data[stock_code][
                ~ta_backtesting_data[stock_code].index.duplicated(keep='first')]
        ta_backtesting_data['HK.01997'].to_csv("STEP 2.csv")

        # Gather all unique dates
        sequence_time = list(unique_time)
        sequence_time.sort()
        # Remove initial data => Used for calculating technical indicators
        sequence_time = sequence_time[self.observation:]

        # Revert back to its initial state (i.e., with 0-99 beginning records)
        self.strategy.set_input_data(self.get_backtesting_init_data())

        # ASSUME All Dataframe has the same shape (Should Be Validated in Prepare Data Step)
        # Start from the 100 records (i.e., defined as self.observation)
        for index in range(self.observation, len(sequence_time)):
            # For each new timestamp, check for each stock if they satisfy the buy/sell condition
            for stock_code in self.stock_list:
                start_time = sequence_time[index - self.observation]
                end_time = sequence_time[index]
                if (start_time not in ta_backtesting_data[stock_code].index) or (
                        end_time not in ta_backtesting_data[stock_code].index):
                    continue

                input_df = ta_backtesting_data[stock_code].loc[start_time:end_time]

                self.strategy.set_input_data_stock_code(stock_code=stock_code, input_df=input_df)

                # At 9:40 AM, if we have a buy signal based on 9:38 and 9:39 AM, we execute it based on 9:40 AM data
                # This assumes 1M time buffer.
                row = input_df.iloc[-1]

                if self.strategy.buy(stock_code):
                    if self.positions.get(stock_code, 0) == 0 and self.capital >= 0:
                        self.positions[stock_code] = self.positions.get(stock_code, row['close'])
                        current_price = row['close']
                        lot_size = self.board_lot_mapping.get(stock_code, 0)
                        qty = lot_size * self.lot_size_multiplier

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
                if self.strategy.sell(stock_code) or index == list(ta_backtesting_data.values())[0].shape[0] - 1:
                    if self.positions.get(stock_code, 0) != 0:
                        current_price = row['close']
                        buy_price = self.positions[stock_code]
                        # Sell all holding assets
                        lot_size = self.board_lot_mapping.get(stock_code, 0)
                        qty = lot_size * self.lot_size_multiplier

                        # Profit = EBIT - fixed charge (15 HKD * 2) - Percentage Charge (Buy Value + Sale Value) * 0.10%
                        EBIT = (current_price - buy_price) * qty
                        profit = EBIT - 2 * self.fixed_charge - (
                                buy_price + current_price) * qty * self.perc_charge / 100 / 2
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

    # def create_tear_sheet(self):
    #     return_ser = pd.read_csv('output.csv', index_col=0, header=0)
    #     return_ser.index = pd.to_datetime(return_ser.index)
    #     # pf.create_returns_tear_sheet(return_ser['HK.00001'])
    #     with open("data.html", "w") as file:
    #         file.write(pf.create_simple_tear_sheet(returns=return_ser['HK.00001']))
