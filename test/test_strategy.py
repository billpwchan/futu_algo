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

from engines import DataProcessingInterface
from strategies.KDJ_Cross import KDJCross
from strategies.MACD_Cross import MACDCross
from util.global_vars import *


class TestStrategy(unittest.TestCase):
    def setUp(self):
        self.stock_code = 'HK.09988'
        self.preparation_date = '2022-04-12'
        self.preparation_data = DataProcessingInterface.get_stock_df_from_file(
            PATH_DATA / self.stock_code / f'{self.stock_code}_{self.preparation_date}_1M.parquet')

        self.target_date = '2022-04-13'
        self.target_data = DataProcessingInterface.get_stock_df_from_file(
            PATH_DATA / self.stock_code / f'{self.stock_code}_{self.target_date}_1M.parquet')

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
                for key in MACD_samples[row['time_key']].keys():
                    self.assertAlmostEqual(latest_row[key].values[0], MACD_samples[row['time_key']][key], delta=0.0006)

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

    def test_KDJ_Cross_calculation(self):
        KDJ_samples = {
            '2022-04-13 15:00:00': {'%k': 52.524, '%d': 53.634, '%j': 50.303},
            '2022-04-13 16:00:00': {'%k': 85.049, '%d': 74.249, '%j': 106.650}
        }

        strategy = KDJCross({self.stock_code: self.preparation_data}, fast_k=9, slow_k=3, slow_d=3, over_buy=80,
                            over_sell=20, observation=100)

        for index, row in self.target_data.iterrows():
            latest_data = row.to_frame().transpose()
            latest_data.reset_index(drop=True, inplace=True)
            strategy.parse_data(latest_data=latest_data)
            if row['time_key'] in KDJ_samples.keys():
                ta_calculations = strategy.get_input_data_stock_code(self.stock_code)
                latest_row = ta_calculations.loc[ta_calculations['time_key'] == row['time_key']]
                for key in KDJ_samples[row['time_key']].keys():
                    self.assertAlmostEqual(latest_row[key].values[0], KDJ_samples[row['time_key']][key], delta=0.0006)

    def test_KDJ_Cross_buy(self):
        buy_decision_keys = ['2022-04-13 09:45:00', '2022-04-13 11:29:00']

        strategy = KDJCross({self.stock_code: self.preparation_data}, fast_k=9, slow_k=3, slow_d=3, over_buy=80,
                            over_sell=20, observation=100)

        for index, row in self.target_data.iterrows():
            latest_data = row.to_frame().transpose()
            latest_data.reset_index(drop=True, inplace=True)
            strategy.parse_data(latest_data=latest_data)
            buy_decision = strategy.buy(self.stock_code)
            if row['time_key'] in buy_decision_keys:
                self.assertTrue(buy_decision)

    def test_KDJ_Cross_sell(self):
        sell_decision_keys = ['2022-04-13 13:13:00', '2022-04-13 13:38:00']

        strategy = KDJCross({self.stock_code: self.preparation_data}, fast_k=9, slow_k=3, slow_d=3, over_buy=80,
                            over_sell=20, observation=100)

        for index, row in self.target_data.iterrows():
            latest_data = row.to_frame().transpose()
            latest_data.reset_index(drop=True, inplace=True)
            strategy.parse_data(latest_data=latest_data)
            sell_decision = strategy.sell(self.stock_code)
            if row['time_key'] in sell_decision_keys:
                self.assertTrue(sell_decision)


if __name__ == '__main__':
    suite = (unittest.TestLoader().loadTestsFromTestCase(TestStrategy))
    unittest.TextTestRunner(verbosity=2).run(suite)
