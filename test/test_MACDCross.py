#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import configparser
import unittest

from futu import *


class MyTestCase(unittest.TestCase):
    def setUp(self):
        self.config = configparser.ConfigParser()
        self.config.read("./config.ini")
        self.quote_ctx = OpenQuoteContext(host=self.config['FutuOpenD.Config'].get('Host'),
                                          port=self.config['FutuOpenD.Config'].getint('Port'))

    def tearDown(self) -> None:
        self.quote_ctx.close()

    def test_something(self):
        ret, data = self.quote_ctx.query_subscription()
        print(data)
        self.assertEqual(True, False)


if __name__ == '__main__':
    unittest.main()
