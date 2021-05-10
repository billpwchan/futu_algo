#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import configparser

from futu import CurKlineHandlerBase, OpenQuoteContext, OpenHKTradeContext, TrdEnv, RET_OK, RET_ERROR

from engines.trading_util import TradingUtil
from util import logger
from util.global_vars import *


class CurKlineHandler(CurKlineHandlerBase):
    def __init__(self, quote_ctx: OpenQuoteContext, trade_ctx: OpenHKTradeContext, input_data: dict = None,
                 strategy_map: dict = None, trd_env: TrdEnv = TrdEnv.SIMULATE):
        if strategy_map is None:
            strategy_map = {}
        self.config = config
        self.default_logger = logger.get_logger('cur_kline')
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
        ret_code, data = super(CurKlineHandler, self).on_recv_rsp(rsp_str)
        if ret_code != RET_OK:
            self.default_logger.error("CurKlineTest: error, msg: %s" % data)
            return RET_ERROR, data

        self.default_logger.info(f'Received:\n {data}')

        # Column Mapping between Subscribed Data <==> Historical Data
        # code, time_key, open, close, high, low, pe_ratio, turnover_rate, volume, turnover, change_rate, last_close
        # code  time_key   open  close   high    low  volume    turnover k_type  last_close
        data.drop(['k_type'], axis=1, inplace=True)
        data.insert(6, 'pe_ratio', 0)
        data.insert(7, 'turnover_rate', 0)
        data.insert(10, 'change_rate', 0)

        # Update Latest Data to the Strategy before Buy/Sell
        strategy = self.strategy_map[data['code'][0]]
        strategy.parse_data(data)

        # Buy/Sell Strategy
        stock_code = data['code'][0]

        if strategy.sell(stock_code=stock_code):
            self.trading_util.place_sell_order(stock_code)

        if strategy.buy(stock_code=stock_code):
            self.trading_util.place_buy_order(stock_code)
