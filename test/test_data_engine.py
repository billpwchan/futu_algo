#  Futu Algo: Algorithmic Trading Framework
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
#  Written by Bill Chan <billpwchan@hotmail.com>, 2022
#  Copyright (c)  billpwchan - All Rights Reserved
import datetime
import unittest
from pathlib import Path

from engines import DataProcessingInterface, YahooFinanceInterface


class TestYahooFinanceInterface(unittest.TestCase):
    def test_get_top_30_hsi_constituents(self):
        top_30_hsi_constituents = YahooFinanceInterface.get_top_30_hsi_constituents()
        self.assertEqual(len(top_30_hsi_constituents), 30)
        for item in top_30_hsi_constituents:
            self.assertRegex(item, r'^[A-Z]{2}.\d{5}$')

    def test_yfinance_code_to_futu_code(self):
        yfinance_code = "9988.HK"
        self.assertEqual(YahooFinanceInterface.yfinance_code_to_futu_code(yfinance_code), "HK.09988")

        self.assertRaises(AssertionError, YahooFinanceInterface.yfinance_code_to_futu_code, "9988")
        self.assertRaises(AssertionError, YahooFinanceInterface.yfinance_code_to_futu_code, "998.HK")
        self.assertRaises(AssertionError, YahooFinanceInterface.yfinance_code_to_futu_code, "9988.HK.HK")
        self.assertRaises(AssertionError, YahooFinanceInterface.yfinance_code_to_futu_code, "09988.H")

    def test_futu_code_to_yfinance_code(self):
        futu_code = "HK.09988"
        self.assertEqual(YahooFinanceInterface.futu_code_to_yfinance_code(futu_code), "9988.HK")

        self.assertRaises(AssertionError, YahooFinanceInterface.futu_code_to_yfinance_code, "HK.9988")
        self.assertRaises(AssertionError, YahooFinanceInterface.futu_code_to_yfinance_code, "H.9988")
        self.assertRaises(AssertionError, YahooFinanceInterface.futu_code_to_yfinance_code, "HK.099899")
        self.assertRaises(AssertionError, YahooFinanceInterface.futu_code_to_yfinance_code, "9988.HK")


class TestDataProcessingInterface(unittest.TestCase):
    def test_get_1M_data_range(self):
        date_range = ['2022-04-11', '2022-04-12', '2022-04-13']
        stock_list = ['HK.09988', 'HK.00700']
        output_dict = DataProcessingInterface.get_1M_data_range(date_range, stock_list)

        self.assertIsInstance(output_dict, dict)
        self.assertCountEqual(output_dict.keys(), stock_list)

    def test_get_custom_interval_data(self):
        target_date = datetime.datetime(2022, 4, 11)
        custom_intervals = [3, 5, 15, 30]
        stock_list = ['HK.09988']
        for custom_interval in custom_intervals:
            output_df = DataProcessingInterface.get_custom_interval_data(target_date, custom_interval, stock_list)[
                stock_list[0]]
            reference_df = DataProcessingInterface.get_stock_df_from_file(
                Path.cwd() / 'test' / 'test_data' / f'HK.09988_2022-04-11_{custom_interval}M.parquet')

            for index, row in output_df.iterrows():
                self.assertEqual(row['code'], reference_df.loc[index, 'code'])
                self.assertEqual(row['time_key'], reference_df.loc[index, 'time_key'],
                                 msg=f'custom_interval: {custom_interval}')
                self.assertAlmostEqual(row['open'], reference_df.loc[index, 'open'], places=2, msg=f"{index} open")
                self.assertAlmostEqual(row['close'], reference_df.loc[index, 'close'], places=2, msg=f"{index} close")
                self.assertAlmostEqual(row['high'], reference_df.loc[index, 'high'], places=2, msg=f"{index} high")
                self.assertAlmostEqual(row['low'], reference_df.loc[index, 'low'], places=2, msg=f"{index} low")
                self.assertAlmostEqual(row['volume'], reference_df.loc[index, 'volume'], places=2,
                                       msg=f"{index} volume")
                self.assertAlmostEqual(row['pe_ratio'], reference_df.loc[index, 'pe_ratio'], places=2,
                                       msg=f"{index} pe_ratio")
                self.assertAlmostEqual(row['turnover_rate'], reference_df.loc[index, 'turnover_rate'], places=2,
                                       msg=f"{index} turnover_rate")
                self.assertAlmostEqual(row['change_rate'], reference_df.loc[index, 'change_rate'], places=2,
                                       msg=f"{index} change_rate")
                self.assertAlmostEqual(row['last_close'], reference_df.loc[index, 'last_close'], places=2,
                                       msg=f"{index} last_close")


if __name__ == '__main__':
    suite_yahoo_finance = (unittest.TestLoader().loadTestsFromTestCase(TestYahooFinanceInterface))
    suite_data_processing = (unittest.TestLoader().loadTestsFromTestCase(TestDataProcessingInterface))
    suite = unittest.TestSuite([suite_yahoo_finance, suite_data_processing])
    unittest.TextTestRunner(verbosity=2).run(suite)
