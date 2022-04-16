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


import unittest
import pandas as pd

from strategies.MACD_Cross import MACDCross
from util.global_vars import *


class StrategyTestCase(unittest.TestCase):
    def setUp(self):
        self.stock_code = 'HK.09988'
        self.preparation_date = '2022-04-12'
        self.preparation_data = pd.read_csv(
            PATH_DATA / self.stock_code / f'{self.stock_code}_{self.preparation_date}_1M.csv',
            index_col=None)
        self.target_date = '2022-04-13'
        self.target_data = pd.read_csv(PATH_DATA / self.stock_code / f'{self.stock_code}_{self.target_date}_1M.csv',
                                       index_col=None)

    def test_MACD_Cross_calculation(self):
        MACD_samples = {
            '2022-04-13 15:30:00': {'MACD': -0.063, 'MACD_signal': -0.023, 'MACD_hist': -0.079},
            '2022-04-13 16:00:00': {'MACD': 0.066, 'MACD_signal': -0.008, 'MACD_hist': 0.148}
        }

        strategy = MACDCross({self.stock_code: self.preparation_data},
                             fast_period=12, slow_period=26, signal_period=9, observation=100)

        for index, row in self.target_data.iterrows():
            latest_data = row.to_frame().transpose()
            latest_data.reset_index(drop=True, inplace=True)
            strategy.parse_data(latest_data=latest_data)
            if row['time_key'] in MACD_samples.keys():
                ta_calculations = strategy.get_input_data_stock_code(self.stock_code)
                latest_row = ta_calculations.loc[ta_calculations['time_key'] == row['time_key']]
                self.assertAlmostEqual(latest_row['MACD'].values[0], MACD_samples[row['time_key']]['MACD'],
                                       delta=0.0006)
                self.assertAlmostEqual(latest_row['MACD_signal'].values[0],
                                       MACD_samples[row['time_key']]['MACD_signal'], delta=0.0006)
                self.assertAlmostEqual(latest_row['MACD_hist'].values[0], MACD_samples[row['time_key']]['MACD_hist'],
                                       delta=0.0006)

    def test_MACD_Cross_buy(self):
        buy_decision_keys = ['2022-04-13 09:52:00', '2022-04-13 11:59:00', ' 2022-04-13 13:32:00',
                             '2022-04-13 13:54:00', '2022-04-13 14:17:00', '2022-04-13 14:52:00', '2022-04-13 15:14:00',
                             '2022-04-13 15:18:00', '2022-04-13 15:45:00']

        strategy = MACDCross({self.stock_code: self.preparation_data}, fast_period=12, slow_period=26, signal_period=9,
                             observation=100)

        for index, row in self.target_data.iterrows():
            latest_data = row.to_frame().transpose()
            latest_data.reset_index(drop=True, inplace=True)
            strategy.parse_data(latest_data=latest_data)
            buy_decision = strategy.buy(self.stock_code)
            if row['time_key'] in buy_decision_keys:
                self.assertTrue(buy_decision)

    def test_MACD_Cross_sell(self):
        sell_decision_keys = ['2022-04-13 09:34:00', '2022-04-13 11:16:00']

        strategy = MACDCross({self.stock_code: self.preparation_data}, fast_period=12, slow_period=26, signal_period=9,
                             observation=100)

        for index, row in self.target_data.iterrows():
            latest_data = row.to_frame().transpose()
            latest_data.reset_index(drop=True, inplace=True)
            strategy.parse_data(latest_data=latest_data)
            sell_decision = strategy.sell(self.stock_code)
            if row['time_key'] in sell_decision_keys:
                self.assertTrue(sell_decision)


if __name__ == '__main__':
    suite = (unittest.TestLoader().loadTestsFromTestCase(StrategyTestCase))
    unittest.TextTestRunner(verbosity=2).run(suite)
