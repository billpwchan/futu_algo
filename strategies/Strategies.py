#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

from abc import ABC, abstractmethod

import pandas as pd


class Strategies(ABC):
    def __init__(self, input_data: pd.DataFrame):
        self.input_data = input_data
        super().__init__()

    @abstractmethod
    def parse_data(self, latest_data: pd.DataFrame):
        pass

    @abstractmethod
    def buy(self) -> bool:
        pass

    @abstractmethod
    def sell(self) -> bool:
        pass
