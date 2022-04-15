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
import unittest

from engines import YahooFinanceInterface


class YahooFinanceInterfaceTestCase(unittest.TestCase):
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


if __name__ == '__main__':
    suite = (unittest.TestLoader().loadTestsFromTestCase(YahooFinanceInterfaceTestCase))
    unittest.TextTestRunner(verbosity=2).run(suite)
