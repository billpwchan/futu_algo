#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

from abc import ABC, abstractmethod

import pandas as pd


class Filters(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def validate(self, input_data: pd.DataFrame, info_data: dict) -> bool:
        """
            Validate if a Stock is worth considering / Monitor in the HFT
            Should mostly use Day K-Line For Evaluation
            Required Columns: open, close, high, low, volume
        :param input_data: DataFrame Object with required columns
        :param info_data: Fundamental Analysis (Company Info. Stock Price. Etc.)
        """
        pass
