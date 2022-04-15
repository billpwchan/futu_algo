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


import configparser
from pathlib import Path

import yaml

PATH = Path.cwd()
PATH_DATA = PATH / 'data'
PATH_DATABASE = PATH / 'database'  # Obsoleted
PATH_FILTER_REPORT = PATH / 'stock_filter_report'

ORDER_RETRY_MAX = 3

if not Path("config.ini").exists():
    raise SystemExit("Missing config.ini. Please use the config_template.ini to create your configuration.")

config = configparser.ConfigParser()
config.read("config.ini")

if not Path("stock_strategy_map.yml").exists():
    raise SystemExit("Missing stock_strategy_map.yml. Please use the stock_strategy_map_template.yml to create your "
                     "configuration.")

with open('stock_strategy_map.yml', 'r') as infile:
    stock_strategy_map = yaml.safe_load(infile)
