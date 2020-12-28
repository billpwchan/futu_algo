#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import numpy as np
import pandas as pd
import talib

import logger
from strategies.Strategies import Strategies

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

    def parse_data(self, latest_data: pd.DataFrame = None):
        # Received New Data => Parse it Now to input_data
        if latest_data is not None:
            stock_list = [latest_data['code'][0]]
            latest_data = pd.concat([latest_data, pd.DataFrame(columns=['MACD', 'MACD_signal', 'MACD_hist'])])
            self.input_data[stock_list[0]] = self.input_data[stock_list[0]].append(latest_data)
        else:
            stock_list = self.input_data.keys()
        for stock_code in stock_list:
            # Need to truncate to a maximum length for low-latency
            self.input_data[stock_code] = self.input_data[stock_code].iloc[-self.OBSERVATION:]
            close = [float(x) for x in self.input_data[stock_code]['close']]
            self.input_data[stock_code]['MACD'], self.input_data[stock_code]['MACD_signal'], \
            self.input_data[stock_code]['MACD_hist'] = talib.MACD(
                np.array(close),
                fastperiod=self.MACD_FAST, slowperiod=self.MACD_SLOW,
                signalperiod=self.MACD_SIGNAL)
            self.input_data[stock_code].reset_index(drop=True, inplace=True)

    # @timeit
    def buy(self, stock_code) -> bool:
        # Crossover between MACD and Signal (Single Point Determined)
        current_record = self.input_data[stock_code].iloc[-1]
        last_record = self.input_data[stock_code].iloc[-2]
        buy_decision = float(current_record['MACD']) > float(current_record['MACD_signal']) and float(
            last_record['MACD']) <= float(last_record['MACD_signal'])
        if buy_decision:
            self.default_logger.info(
                f"Buy Decision: {buy_decision} based on \n {last_record.to_frame().transpose()} \n {current_record.to_frame().transpose()} ")
        return buy_decision

    # @timeit
    def sell(self, stock_code) -> bool:
        # Crossover between Signal and MACD (Single Point Determined)
        current_record = self.input_data[stock_code].iloc[-1]
        last_record = self.input_data[stock_code].iloc[-2]
        sell_decision = float(current_record['MACD']) < float(current_record['MACD_signal']) and float(
            last_record['MACD']) >= float(last_record['MACD_signal'])
        if sell_decision:
            self.default_logger.info(
                f"Sell Decision: {sell_decision} based on \n {last_record.to_frame().transpose()} \n {current_record.to_frame().transpose()}")
        return sell_decision
