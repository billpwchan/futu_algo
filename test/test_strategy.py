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


class StrategyTestCase(unittest.TestCase):
    # def setUp(self):
    #     self.stock_code = 'HK.09988'
    #     self.complete_data = pd.read_csv('./test/test_data/test_data.csv', index_col=None)
    #     self.input_data = self.complete_data.iloc[:150, :]
    #     self.test_data = self.complete_data.iloc[150:, :]
    #     self.strategy = QuantLegendary({self.stock_code: self.input_data}, observation=150)
    #
    # def test_buy(self):
    #     for index, row in self.test_data.iterrows():
    #         latest_data = row.to_frame().transpose()
    #         latest_data.reset_index(drop=True, inplace=True)
    #         self.strategy.parse_data(latest_data=latest_data)
    #         self.strategy.buy(self.stock_code)
    #     self.assertEqual(True, True)
    #
    # def test_sell(self):
    #     for index, row in self.test_data.iterrows():
    #         latest_data = row.to_frame().transpose()
    #         latest_data.reset_index(drop=True, inplace=True)
    #         self.strategy.parse_data(latest_data=latest_data)
    #         self.strategy.sell(self.stock_code)
    #     self.assertEqual(True, True)
    def test_buy(self):
        self.assertEqual(True, True)


if __name__ == '__main__':
    unittest.main()
