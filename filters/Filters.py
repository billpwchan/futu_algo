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
#  C abc import ABC, abstractmethod

import pandas as pd


class Filters(ABC):
    def __init__(self):
        """
        MAKE SURE THE FILE NAME IS EXACTLY THE SAME EXCEPT FOR ADDING UNDERSCORES!
        This is required for dynamic instantiation
        """
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
