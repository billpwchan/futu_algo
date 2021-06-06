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
#  Crt json

from futu import OpenHKTradeContext, OpenQuoteContext, RET_ERROR, RET_OK, StockQuoteHandlerBase, TrdEnv

from engines.trading_util import TradingUtil
from util import logger
from util.global_vars import *


class StockQuoteHandler(StockQuoteHandlerBase):
    def __init__(self, quote_ctx: OpenQuoteContext, trade_ctx: OpenHKTradeContext, input_data: dict = None,
                 strategy_map: dict = None, trd_env: TrdEnv = TrdEnv.SIMULATE):
        if strategy_map is None:
            strategy_map = {}
        self.config = config
        self.default_logger = logger.get_logger('stock_quote')
        self.quote_ctx = quote_ctx
        self.trade_ctx = trade_ctx
        self.input_data = input_data
        self.strategy_map = strategy_map
        self.trd_env = trd_env
        self.trading_util = TradingUtil(self.quote_ctx, self.trade_ctx, self.trd_env)
        super().__init__()

    def set_input_data(self, input_data: dict):
        self.input_data = input_data.copy()

    def on_recv_rsp(self, rsp_str):
        ret_code, data = super(StockQuoteHandler, self).on_recv_rsp(rsp_str)
        if ret_code != RET_OK:
            self.default_logger.error("StockQuoteTest: error, msg: %s" % data)
            return RET_ERROR, data

        # Column Mapping between Subscribed Data <==> Historical Data
        data['time_key'] = data['data_date'] + ' ' + data['data_time']
        data = data[
            ['code', 'time_key', 'open_price', 'last_price', 'high_price', 'low_price', 'amplitude',
             'turnover_rate', 'volume', 'turnover', 'amplitude', 'prev_close_price']]
        self.default_logger.info(
            f"Received: \n {data[['code', 'time_key', 'last_price', 'volume', 'prev_close_price']]}")
        data.columns = json.loads(self.config.get('FutuOpenD.DataFormat', 'HistoryDataFormat'))

        # Update Latest Data to the Strategy before Buy/Sell
        strategy = self.strategy_map[data['code'][0]]
        strategy.parse_data(data)

        # Buy/Sell Strategy
        stock_code = data['code'][0]

        if strategy.sell(stock_code=stock_code):
            self.trading_util.place_sell_order(stock_code)

        if strategy.buy(stock_code=stock_code):
            self.trading_util.place_buy_order(stock_code)
