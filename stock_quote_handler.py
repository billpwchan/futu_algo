#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2021

import configparser
import json

from futu import StockQuoteHandlerBase, OpenQuoteContext, OpenHKTradeContext, TrdEnv, logger, RET_OK, RET_ERROR, \
    TrdSide, OrderType

from strategies.MACDCross import MACDCross
from strategies.Strategies import Strategies


class StockQuoteHandler(StockQuoteHandlerBase):
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
        self.strategy.parse_data(data)

        # Buy/Sell Strategy
        stock_code = data['code'][0]

        if self.strategy.sell(stock_code=stock_code):
            self.default_logger.info(f"SELL DECISION for {stock_code} is triggered.")
            ret_code, position_data = self.trade_ctx.position_list_query(code=stock_code, pl_ratio_min=None,
                                                                         pl_ratio_max=None,
                                                                         trd_env=self.trd_env, acc_id=0, acc_index=0,
                                                                         refresh_cache=False)
            if ret_code != RET_OK:
                self.default_logger.error(f"Cannot acquire account position {data}")
                raise Exception('账户信息获取失败: {}'.format(data))
            if position_data.empty:
                self.default_logger.info(f"Account does not hold any position for stock {stock_code}")
                return

            position_data = position_data.set_index('code')
            can_sell_qty = int(position_data['can_sell_qty'][stock_code])

            # 进行清仓
            if can_sell_qty > 0:
                ret_code, market_data = self.quote_ctx.get_market_snapshot([stock_code])
                if ret_code != RET_OK:
                    self.default_logger.error(f"Cannot acquire market snapshot {data}")
                    raise Exception('市场快照数据获取异常 {}'.format(market_data))
                cur_price = market_data.iloc[0]['last_price']
                lot_size = market_data.iloc[0]['lot_size']
                if can_sell_qty > lot_size:
                    can_sell_qty = lot_size
                    self.default_logger.error(f"Can Sell Quantity is larger than Lot Size for stock {stock_code}")

                # ret_code, order_data = self.quote_ctx.get_order_book(stock_code)  # 获取摆盘
                # if ret_code != RET_OK:
                #     self.default_logger.error("can't get orderbook, retrying:{}".format(order_data))
                #
                # bid1_price = order_data['Bid'][0][0]  # 取得买一价

                ret_code, ret_data = self.trade_ctx.place_order(
                    price=cur_price,
                    qty=can_sell_qty,
                    code=stock_code,
                    trd_side=TrdSide.SELL,
                    order_type=OrderType.NORMAL,
                    trd_env=self.trd_env)
                if ret_code == RET_OK:
                    self.default_logger.info(
                        'MAKE SELL ORDER code = {} price = {} quantity = {}'.format(stock_code, cur_price,
                                                                                    can_sell_qty))
                else:
                    self.default_logger.error('MAKE SELL ORDER FAILURE: {}'.format(ret_data))

        if self.strategy.buy(stock_code=stock_code):
            self.default_logger.info(f"BUY DECISION for {stock_code} is triggered")
            ret_code, position_data = self.trade_ctx.position_list_query(code=stock_code, pl_ratio_min=None,
                                                                         pl_ratio_max=None,
                                                                         trd_env=self.trd_env, acc_id=0, acc_index=0,
                                                                         refresh_cache=False)
            if ret_code != RET_OK:
                self.default_logger.error(f"Cannot acquire account position {data}")
                raise Exception('账户信息获取失败: {}'.format(data))
            if not position_data.empty:
                self.default_logger.info(f"Account holds any position for stock {stock_code}")
                return

            ret_code, market_data = self.quote_ctx.get_market_snapshot([stock_code])
            if ret_code != RET_OK:
                self.default_logger.error(f"Cannot acquire market snapshot {data}")
                raise Exception('市场快照数据获取异常 {}'.format(market_data))
            cur_price = market_data.iloc[0]['last_price']
            lot_size = market_data.iloc[0]['lot_size']

            # ret_code, order_data = self.quote_ctx.get_order_book(stock_code)  # 获取摆盘
            # if ret_code != RET_OK:
            #     self.default_logger.error("can't get orderbook, retrying:{}".format(order_data))
            #
            # bid1_price = order_data['Bid'][0][0]  # 取得买一价

            ret_code, ret_data = self.trade_ctx.place_order(
                price=cur_price,
                qty=lot_size,
                code=stock_code,
                trd_side=TrdSide.BUY,
                order_type=OrderType.NORMAL,
                trd_env=self.trd_env)
            if ret_code == RET_OK:
                self.default_logger.info(
                    'MAKE BUY ORDER\n\tcode = {} price = {} quantity = {}'.format(stock_code, cur_price, lot_size))
            else:
                self.default_logger.error('MAKE BUY ORDER FAILURE: {}'.format(ret_data))
