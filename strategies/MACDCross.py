#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import numpy as np
import pandas as pd
import talib

from strategies.Strategies import Strategies
from trading_utils import timeit

pd.options.mode.chained_assignment = None  # default='warn'


class MACDCross(Strategies):
    def __init__(self, input_data: pd.DataFrame, fast_period=12, slow_period=26, signal_period=9):
        self.MACD_FAST = fast_period
        self.MACD_SLOW = slow_period
        self.MACD_SIGNAL = signal_period
        super().__init__(input_data)
        self.parse_data()

    def parse_data(self, latest_data: pd.DataFrame = None):
        # Received New Data => Parse it Now to input_data
        if latest_data is not None:
            latest_data = pd.concat([latest_data, pd.DataFrame(columns=['MACD', 'MACD_signal', 'MACD_hist'])])
            self.input_data = self.input_data.append(latest_data)
        # Need to truncate to a maximum length for low-latency
        self.input_data = self.input_data.iloc[-40:]
        close = [float(x) for x in self.input_data['close']]
        self.input_data['MACD'], self.input_data['MACD_signal'], self.input_data['MACD_hist'] = talib.MACD(
            np.array(close),
            fastperiod=self.MACD_FAST, slowperiod=self.MACD_SLOW,
            signalperiod=self.MACD_SIGNAL)
        self.input_data.reset_index(drop=True, inplace=True)
        return

    @timeit
    def buy(self) -> bool:
        return True

    @timeit
    def sell(self) -> bool:
        return True
