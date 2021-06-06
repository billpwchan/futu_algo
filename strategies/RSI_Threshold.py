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


class RSIThreshold(Strategies):
    def __init__(self, input_data: dict, rsi_1=6, rsi_2=12, rsi_3=24, lower_rsi=30, upper_rsi=70, observation=100):
        """
        Initialize RSI-Threshold Strategy Instance
        :param input_data:
        :param rsi_1: RSI Period 1 (Default = 6)
        :param rsi_2: RSI Period 2 (Default = 12)
        :param rsi_3: RSI Period 3 (Default = 24)
        :param lower_rsi: Lower RSI Threshold (Default = 30)
        :param upper_rsi: Upper RSI Threshold (Default = 70)
        :param observation: Observation Period in Dataframe (Default = 100)
        """
        self.RSI_1 = rsi_1
        self.RSI_2 = rsi_2
        self.RSI_3 = rsi_3
        self.LOWER_RSI = lower_rsi
        self.UPPER_RSI = upper_rsi
        self.OBSERVATION = observation
        self.default_logger = logger.get_logger("rsi_threshold")

        super().__init__(input_data)
        self.parse_data()

    def __compute_RSI(self, stock_code, time_window):
        diff = self.input_data[stock_code]['close'].diff(1).dropna()  # diff in one field(one day)

        # this preservers dimensions off diff values
        up_chg = 0 * diff
        down_chg = 0 * diff

        # up change is equal to the positive difference, otherwise equal to zero
        up_chg[diff > 0] = diff[diff > 0]

        # down change is equal to negative difference, otherwise equal to zero
        down_chg[diff < 0] = diff[diff < 0]

        # check pandas documentation for ewm
        # https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.ewm.html
        # values are related to exponential decay
        # we set com=time_window-1 so we get decay alpha=1/time_window
        up_chg_avg = up_chg.ewm(com=time_window - 1, min_periods=time_window).mean()
        down_chg_avg = down_chg.ewm(com=time_window - 1, min_periods=time_window).mean()

        rs = abs(up_chg_avg / down_chg_avg)
        rsi = 100 - 100 / (1 + rs)
        return rsi

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
            latest_data = pd.concat([latest_data, pd.DataFrame(columns=['rsi_1', 'rsi_2', 'rsi_3'])])
            self.input_data[stock_list[0]] = self.input_data[stock_list[0]].append(latest_data)
        else:
            stock_list = self.input_data.keys()

        # Calculate EMA for the stock_list
        for stock_code in stock_list:
            # Need to truncate to a maximum length for low-latency
            if not backtesting:
                self.input_data[stock_code] = self.input_data[stock_code].iloc[
                                              -min(self.OBSERVATION, self.input_data[stock_code].shape[0]):]
            self.input_data[stock_code][['open', 'close', 'high', 'low']] = self.input_data[stock_code][
                ['open', 'close', 'high', 'low']].apply(pd.to_numeric)

            self.input_data[stock_code]['rsi_1'] = self.__compute_RSI(stock_code=stock_code, time_window=self.RSI_1)
            self.input_data[stock_code]['rsi_2'] = self.__compute_RSI(stock_code=stock_code, time_window=self.RSI_2)
            self.input_data[stock_code]['rsi_3'] = self.__compute_RSI(stock_code=stock_code, time_window=self.RSI_3)

            self.input_data[stock_code].reset_index(drop=True, inplace=True)

    def buy(self, stock_code) -> bool:
        current_record = self.input_data[stock_code].iloc[-2]
        previous_record = self.input_data[stock_code].iloc[-3]
        # Buy Decision based on RSI值超过了超卖线
        buy_decision = current_record['rsi_1'] < self.LOWER_RSI < previous_record['rsi_1']

        if buy_decision:
            self.default_logger.info(
                f"Buy Decision: {current_record['time_key']} based on \n {pd.concat([previous_record.to_frame().transpose(), current_record.to_frame().transpose()], axis=0)}")

        return buy_decision

    def sell(self, stock_code) -> bool:
        current_record = self.input_data[stock_code].iloc[-2]
        previous_record = self.input_data[stock_code].iloc[-3]
        # Sell Decision based on RSI值超过了超买线
        sell_decision = current_record['rsi_1'] > self.UPPER_RSI > previous_record['rsi_1']

        if sell_decision:
            self.default_logger.info(
                f"Sell Decision: {current_record['time_key']} based on \n {pd.concat([previous_record.to_frame().transpose(), current_record.to_frame().transpose()], axis=0)}")
        return sell_decision
