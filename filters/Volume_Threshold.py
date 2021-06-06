#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
import pandas as pd

from filters.Filters import Filters


class VolumeThreshold(Filters):
    def __init__(self, volume_threshold: int = 10 ** 7):
        self.VOLUME_THRESHOLD = volume_threshold
        super().__init__()

    def validate(self, input_data: pd.DataFrame, info_data: dict) -> bool:
        """
            Return True if the mean close price for the previous 30 days are larger than 1 HKD.
        :param input_data: Yahoo Finance Quantitative Data (Price, Volume, etc.)
        :param info_data: Yahoo Finance Fundamental Data (Company Description. PE Ratio, Etc.)
        :return:
        """
        if input_data.empty:
            return False
        last_30_records = input_data.iloc[-min(30, input_data.shape[0]):]
        return (last_30_records['close'].mean() *
                last_30_records['volume'].mean() > self.VOLUME_THRESHOLD)
