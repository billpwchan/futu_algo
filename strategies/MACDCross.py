#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import numpy as np
import pandas as pd
import talib

from strategies.Strategies import Strategies

pd.options.mode.chained_assignment = None  # default='warn'


class MACDCross(Strategies):
    def __init__(self, input_data: pd.DataFrame, fast_period=12, slow_period=26, signal_period=9):
        self.MACD_FAST = fast_period
        self.MACD_SLOW = slow_period
        self.MACD_SIGNAL = signal_period
        super().__init__(input_data)

    def parse_data(self):
        # Need to truncate to a maximum length for low-latency
        self.input_data = self.input_data.iloc[-40:]
        close = [float(x) for x in self.input_data['close']]
        self.input_data['MACD'], self.input_data['MACD_signal'], self.input_data['MACD_hist'] = talib.MACD(
            np.array(close),
            fastperiod=self.MACD_FAST, slowperiod=self.MACD_SLOW,
            signalperiod=self.MACD_SIGNAL)
        return self.input_data

    def buy(self, latest_data: pd.DataFrame) -> bool:
        return True

    def sell(self, latest_data: pd.DataFrame) -> bool:
        return True
