#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2021

import numpy as np
import pandas as pd
import talib as talib

import logger
from strategies.Strategies import Strategies

pd.options.mode.chained_assignment = None  # default='warn'
talib.set_compatibility(1)


class RSIThreshold(Strategies):
    def __init__(self, input_data: dict, rsi_1=6, rsi_2=12, rsi_3=24, lower_rsi=20, upper_rsi=80, observation=100):
        """
        Initialize RSI-Threshold Strategy Instance
        :param input_data:
        :param rsi_1: RSI Period 1 (Default = 6)
        :param rsi_2: RSI Period 2 (Default = 12)
        :param rsi_3: RSI Period 3 (Default = 24)
        :param lower_rsi: Lower RSI Threshold (Default = 20)
        :param upper_rsi: Upper RSI Threshold (Default = 80)
        :param observation: Observation Period in Dataframe (Default = 100)
        """
        self.RSI_1 = rsi_1
        self.RSI_2 = rsi_2
        self.RSI_3 = rsi_3
        self.LOWER_RSI = lower_rsi
        self.UPPER_RSI = upper_rsi
        self.OBSERVATION = observation
        self.default_logger = logger.get_logger("kdj_cross")

        super().__init__(input_data)
        self.parse_data()

    def parse_data(self, latest_data: pd.DataFrame = None):
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
            self.input_data[stock_code] = self.input_data[stock_code].iloc[-self.OBSERVATION:]
            self.input_data[stock_code][['open', 'close', 'high', 'low']] = self.input_data[stock_code][
                ['open', 'close', 'high', 'low']].apply(pd.to_numeric)

            close = [float(x) for x in self.input_data[stock_code]['close']]
            self.input_data[stock_code]['rsi_1'] = talib.RSI(np.array(close), timeperiod=self.RSI_1)
            self.input_data[stock_code]['rsi_2'] = talib.RSI(np.array(close), timeperiod=self.RSI_2)
            self.input_data[stock_code]['rsi_3'] = talib.RSI(np.array(close), timeperiod=self.RSI_3)

            self.input_data[stock_code].reset_index(drop=True, inplace=True)

    def buy(self, stock_code) -> bool:
        current_record = self.input_data[stock_code].iloc[-1]
        last_record = self.input_data[stock_code].iloc[-2]
        # Buy Decision based on RSI值超过了超卖线
        buy_decision = current_record['rsi_1'] < self.LOWER_RSI < last_record['rsi_1']

        if buy_decision:
            self.default_logger.info(
                f"Buy Decision: {current_record['time_key']} based on \n {pd.concat([last_record.to_frame().transpose(), current_record.to_frame().transpose()], axis=0)}")

        return buy_decision

    def sell(self, stock_code) -> bool:

        current_record = self.input_data[stock_code].iloc[-1]
        last_record = self.input_data[stock_code].iloc[-2]
        # Sell Decision based on RSI值超过了超买线
        sell_decision = current_record['rsi_1'] > self.UPPER_RSI > last_record['rsi_1']

        if sell_decision:
            self.default_logger.info(
                f"Sell Decision: {current_record['time_key']} based on \n {pd.concat([last_record.to_frame().transpose(), current_record.to_frame().transpose()], axis=0)}")
        return sell_decision
