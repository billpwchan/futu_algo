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
import time
from pathlib import Path

import yaml

PATH = Path.cwd()
PATH_CONFIG = PATH / 'config'
PATH_DATA = PATH / 'data'
PATH_DATABASE = PATH / 'database'  # Obsoleted
PATH_FILTERS = PATH / 'filters'
PATH_STRATEGIES = PATH / 'strategies'
PATH_FILTER_REPORT = PATH / 'stock_filter_report'
PATH_STRATEGY_REPORT = PATH / 'stock_strategy_report'
PATH_LOG = PATH / 'log'

DATETIME_FORMAT_DW = '%Y-%m-%d'
DATETIME_FORMAT_M = ''

ORDER_RETRY_MAX = 3

if not (PATH_CONFIG / 'config.ini').is_file():
    if not (PATH_CONFIG / 'config_template.ini').is_file():
        raise SystemExit(
            "Missing config/config.ini. Please use the config/config_template.ini to create your configuration.")
    else:
        print("Please rename config_template.ini to config.ini and update it.")

config = configparser.ConfigParser()
config.read(
    PATH_CONFIG / 'config.ini' if (PATH_CONFIG / 'config.ini').is_file() else PATH_CONFIG / 'config_template.ini')

if not (PATH_CONFIG / "stock_strategy_map.yml").is_file():
    if not (PATH_CONFIG / "stock_strategy_map_template.yml").is_file():
        raise SystemExit(
            "Missing stock_strategy_map.yml. Please use the stock_strategy_map_template.yml to create your configuration.")
    else:
        print("Please rename stock_strategy_map_template.yml to stock_strategy_map.yml and update it.")

with open(PATH_CONFIG / "stock_strategy_map.yml" if (PATH_CONFIG / "stock_strategy_map.yml").is_file()
          else PATH_CONFIG / "stock_strategy_map_template.yml", 'r') as infile:
    stock_strategy_map = yaml.safe_load(infile)


def timeit(method):
    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()
        if 'log_time' in kw:
            name = kw.get('log_name', method.__name__.upper())
            kw['log_time'][name] = int((te - ts) * 1000)
        else:
            print('%r  %2.2f ms' % (method.__name__, (te - ts) * 1000))
        return result

    return timed
