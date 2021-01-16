#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

from data_engine import HKEXInterface


class StockFilter:
    def __init__(self):
        self.full_stock_list = HKEXInterface.get_security_list_full()
