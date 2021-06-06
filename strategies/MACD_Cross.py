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
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
#  Crt pandas as pd

from strategies.Strategies import Strategies
from util import logger

pd.options.mode.chained_assignment = None  # default='warn'


class MACDCross(Strategies):
    def __init__(self, input_data: dict, fast_period=12, slow_period=26, signal_period=9, observation=100):
        self.MACD_FAST = fast_period
        self.MACD_SLOW = slow_period
        self.MACD_SIGNAL = signal_period
        self.OBSERVATION = observation
        self.default_logger = logger.get_logger("macd_cross")

        super().__init__(input_data)
        self.parse_data()

    def parse_data(self, latest_data: pd.DataFrame = None, backtesting: bool = False):
        # Received New Data => Parse it Now to input_data
        if latest_data is not None:
            # Only need to update MACD for the stock_code with new data
            stock_list = [latest_data['code'][0]]

            # Remove records with duplicate time_key. Always use the latest data to override
            time_key = latest_data['time_key'][0]
            self.input_data[stock_list[0]].drop(
                self.input_data[stock_list[0]][self.input_data[stock_list[0]].time_key == time_key].index,
                inplace=True)
            # Append empty columns and concat at the bottom
            latest_data = pd.concat([latest_data, pd.DataFrame(columns=['MACD', 'MACD_signal', 'MACD_hist'])])
            self.input_data[stock_list[0]] = self.input_data[stock_list[0]].append(latest_data)
        else:
            stock_list = self.input_data.keys()

        # Calculate MACD for the stock_list
        for stock_code in stock_list:
            # Need to truncate to a maximum length for low-latency
            if not backtesting:
                self.input_data[stock_code] = self.input_data[stock_code].iloc[
                                              -min(self.OBSERVATION, self.input_data[stock_code].shape[0]):]
            self.input_data[stock_code][['open', 'close', 'high', 'low']] = self.input_data[stock_code][
                ['open', 'close', 'high', 'low']].apply(pd.to_numeric)

            # MACD = EMA-Fast - EMA-Slow. Signal = EMA(MACD, Smooth-period)
            ema_fast = self.input_data[stock_code]['close'].ewm(span=self.MACD_FAST, adjust=False).mean()
            ema_slow = self.input_data[stock_code]['close'].ewm(span=self.MACD_SLOW, adjust=False).mean()
            self.input_data[stock_code]['MACD'] = ema_fast - ema_slow
            self.input_data[stock_code]['MACD_signal'] = self.input_data[stock_code]['MACD'].ewm(span=self.MACD_SIGNAL,
                                                                                                 adjust=False).mean()
            # MACD_hist = (MACD - MACD_signal) * 2
            self.input_data[stock_code]['MACD_hist'] = (self.input_data[stock_code]['MACD'] -
                                                        self.input_data[stock_code]['MACD_signal']) * 2

            self.input_data[stock_code].reset_index(drop=True, inplace=True)

    # @timeit
    def buy(self, stock_code) -> bool:
        # Crossover between MACD and Signal (Single Point Determined)
        current_record = self.input_data[stock_code].iloc[-2]
        previous_record = self.input_data[stock_code].iloc[-3]
        buy_decision = float(current_record['MACD']) > float(current_record['MACD_signal']) and float(
            previous_record['MACD']) <= float(previous_record['MACD_signal'])
        if buy_decision:
            self.default_logger.info(
                f"Buy Decision: {current_record['time_key']} based on \n {pd.concat([previous_record.to_frame().transpose(), current_record.to_frame().transpose()], axis=0)}")

        return buy_decision

    # @timeit
    def sell(self, stock_code) -> bool:
        # Crossover between Signal and MACD (Single Point Determined)
        current_record = self.input_data[stock_code].iloc[-2]
        previous_record = self.input_data[stock_code].iloc[-3]
        sell_decision = float(current_record['MACD']) < float(current_record['MACD_signal']) and float(
            previous_record['MACD']) >= float(previous_record['MACD_signal'])
        if sell_decision:
            self.default_logger.info(
                f"Sell Decision: {current_record['time_key']} based on \n {pd.concat([previous_record.to_frame().transpose(), current_record.to_frame().transpose()], axis=0)}")
        return sell_decision
