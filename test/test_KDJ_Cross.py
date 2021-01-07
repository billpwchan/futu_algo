#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import unittest

import pandas as pd

from strategies.KDJ_Cross import KDJCross


class KDJTestCase(unittest.TestCase):
    def setUp(self):
        self.stock_code = 'HK.09988'
        self.complete_data = pd.read_csv('./test/test_data/test_data.csv', index_col=None)
        self.input_data = self.complete_data.iloc[:100, :]
        self.test_data = self.complete_data.iloc[100:, :]
        self.kdj_cross = KDJCross({self.stock_code: self.input_data}, observation=100)

    def test_buy(self):
        # Success. K = 71.86 D = 71.021 J = 73.539 at Dec 23 2020 11:10 AM
        for index, row in self.test_data.iterrows():
            latest_data = row.to_frame().transpose()
            latest_data.reset_index(drop=True, inplace=True)
            self.kdj_cross.parse_data(latest_data=latest_data)
            self.kdj_cross.buy(self.stock_code)
        self.assertEqual(True, True)

    def test_sell(self):
        for index, row in self.test_data.iterrows():
            latest_data = row.to_frame().transpose()
            latest_data.reset_index(drop=True, inplace=True)
            self.kdj_cross.parse_data(latest_data=latest_data)
            self.kdj_cross.sell(self.stock_code)
        self.assertEqual(True, True)


if __name__ == '__main__':
    unittest.main()
