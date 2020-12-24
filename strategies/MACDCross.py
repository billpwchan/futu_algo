#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import numpy as np
import pandas as pd
import talib

from strategies import Strategies


class MACDCross(Strategies):
    def __int__(self, input_data: pd.DataFrame):
        super().__init__(input_data)

    def parse_data(self):
        close = [float(x) for x in self.input_data['close']]
        self.input_data['EMA12'] = talib.EMA(np.array(close), timeperiod=12)
        self.input_data['EMA26'] = talib.EMA(np.array(close), timeperiod=26)

        self.input_data['MACD'], self.input_data['MACDsignal'], self.input_data['MACDhist'] = talib.MACD(
            np.array(close),
            fastperiod=12, slowperiod=26,
            signalperiod=9)
        return self.input_data
