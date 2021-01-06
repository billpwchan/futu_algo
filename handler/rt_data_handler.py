#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2021

import configparser
import json

from futu import RTDataHandlerBase, OpenQuoteContext, OpenHKTradeContext, TrdEnv, RET_OK, RET_ERROR

import logger
from handler.trading_util import TradingUtil
from strategies.MACDCross import MACDCross
from strategies.Strategies import Strategies


class RTDataHandler(RTDataHandlerBase):
    def __init__(self, quote_ctx: OpenQuoteContext, trade_ctx: OpenHKTradeContext, input_data: dict = None,
                 strategy: Strategies = MACDCross, trd_env: TrdEnv = TrdEnv.SIMULATE):
        self.config = configparser.ConfigParser()
        self.config.read("config.ini")
        self.default_logger = logger.get_logger('stock_quote')
        self.quote_ctx = quote_ctx
        self.trade_ctx = trade_ctx
        self.input_data = input_data
        self.strategy = strategy
        self.trd_env = trd_env
        self.trading_util = TradingUtil(self.quote_ctx, self.trade_ctx, self.trd_env)
        super().__init__()

    def set_input_data(self, input_data: dict):
        self.input_data = input_data.copy()

    def on_recv_rsp(self, rsp_str):
        ret_code, data = super(RTDataHandler, self).on_recv_rsp(rsp_str)
        if ret_code != RET_OK:
            self.default_logger.error("RTDataTest: error, msg: %s" % data)
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
        self.strategy.parse_data(data)

        # Buy/Sell Strategy
        stock_code = data['code'][0]

        if self.strategy.sell(stock_code=stock_code):
            self.trading_util.place_sell_order(stock_code)

        if self.strategy.buy(stock_code=stock_code):
            self.trading_util.place_buy_order(stock_code)
