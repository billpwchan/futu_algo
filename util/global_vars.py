#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
import configparser
from pathlib import Path

import yaml

if not Path("config.ini").exists():
    raise SystemExit("Missing config.ini. Please use the config_template.ini to create your configuration.")

config = configparser.ConfigParser()
config.read("config.ini")

if not Path("stock_strategy_map.yml").exists():
    raise SystemExit("Missing stock_strategy_map.yml. Please use the stock_strategy_map_template.yml to create your "
                     "configuration.")

with open('stock_strategy_map.yml', 'r') as infile:
    stock_strategy_map = yaml.safe_load(infile)
