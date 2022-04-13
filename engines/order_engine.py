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


import time

from futu import ModifyOrderOp, OpenHKTradeContext, OpenQuoteContext, OrderStatus, OrderType, RET_OK, \
    TradeDealHandlerBase, TradeOrderHandlerBase, TrdAccType, \
    TrdEnv, TrdSide

from util import logger
from util.global_vars import ORDER_RETRY_MAX


class OnOrderClass(TradeOrderHandlerBase):
    def on_recv_rsp(self, rsp_pb):
        ret, data = super(OnOrderClass, self).on_recv_rsp(rsp_pb)
        if ret == RET_OK:
            OrderEngine.on_order_status(data)


class OnFillClass(TradeDealHandlerBase):
    def on_recv_rsp(self, rsp_pb):
        ret, data = super(OnFillClass, self).on_recv_rsp(rsp_pb)
        if ret == RET_OK:
            OrderEngine.on_fill(data)


class OrderEngine:
    def __init__(self, quote_ctx: OpenQuoteContext, trade_ctx: OpenHKTradeContext, trd_env: TrdEnv = TrdEnv.SIMULATE,
                 acc_type: TrdAccType = TrdAccType.CASH):
        self.default_logger = logger.get_logger('trading_util')
        self.quote_ctx = quote_ctx
        self.trade_ctx = trade_ctx
        self.trade_ctx.set_handler(OnOrderClass())
        self.trade_ctx.set_handler(OnFillClass())
        self.trd_env = trd_env
        self.acc_type = acc_type
        self.acc_id = self.__get_acc_list()['acc_id'].values[0]
        self.status_filter_list = [OrderStatus.WAITING_SUBMIT, OrderStatus.SUBMITTING,
                                   OrderStatus.SUBMITTED, OrderStatus.FILLED_PART]

    @staticmethod
    def on_fill(data):
        pass

    @staticmethod
    def on_order_status(data):
        pass
        # if data['code'][0] == TRADING_SECURITY:
        #     show_order_status(data)

    def __get_acc_list(self):
        ret, acc_list = self.trade_ctx.get_acc_list()
        if ret != RET_OK:
            self.default_logger.error(f'Get account list failed: {acc_list}')
            return None
        return acc_list[(acc_list['trd_env'] == self.trd_env) & (acc_list['acc_type'] == self.acc_type)]

    def get_holding_position_qty(self, stock_code):
        holding_position = 0
        ret, data = self.trade_ctx.position_list_query(code=stock_code, trd_env=self.trd_env, acc_id=self.acc_id)
        if ret != RET_OK:
            self.default_logger.error(f'Get position list failed: {data}')
            return None
        else:
            if data.shape[0] > 0:
                holding_position = data['qty'][0]
            self.default_logger.info(f'[Position] The position of {stock_code} is {holding_position}')
        return holding_position

    def get_holding_position(self, stock_code: str = ''):
        ret, data = self.trade_ctx.position_list_query(code=stock_code, pl_ratio_min=None, pl_ratio_max=None,
                                                       trd_env=self.trd_env, acc_id=self.acc_id)
        if ret != RET_OK:
            self.default_logger.error(f'Get position list failed: {data}')
            return None
        else:
            return data

    def get_ask_and_bid(self, stock_code):
        ret, data = self.quote_ctx.get_order_book(stock_code, num=1)
        if ret != RET_OK:
            self.default_logger.info(f'Get order book failed: {data}')
            return None, None
        return data['Ask'][0][0], data['Bid'][0][0]

    def get_market_snapshot(self, stock_code):
        # Use Current Market Price / Bid-1 Buy Price to place a buy order
        ret_code, market_data = self.quote_ctx.get_market_snapshot([stock_code])
        if ret_code != RET_OK:
            self.default_logger.error(f"Cannot acquire market snapshot {market_data}")
            return None
        return market_data.iloc[0]

    def get_order_book(self, stock_code):
        ret_code, order_list_data = self.trade_ctx.order_list_query(order_id="",
                                                                    status_filter_list=self.status_filter_list,
                                                                    code=stock_code, start='', end='',
                                                                    trd_env=self.trd_env,
                                                                    acc_id=self.acc_id, refresh_cache=False)
        if ret_code != RET_OK:
            self.default_logger.error(f"Cannot acquire order list {order_list_data}")
            return None
        return order_list_data

    # Check the buying power is enough for the quantity
    def is_valid_quantity(self, stock_code, quantity, price):
        ret, data = self.trade_ctx.acctradinginfo_query(order_type=OrderType.NORMAL, code=stock_code, price=price,
                                                        trd_env=self.trd_env, acc_id=self.acc_id)
        if ret != RET_OK:
            self.default_logger.err(f'Get max long/short quantity failed: {data}')
            return False
        max_can_buy = data['max_cash_buy'][0]
        max_can_sell = data['max_sell_short'][0]
        if quantity > 0:
            return quantity < max_can_buy
        elif quantity < 0:
            return abs(quantity) < max_can_sell
        else:
            return False

    def check_unfilled_orders(self, stock_code, trd_side) -> bool:
        # Check if an order has already been made but not filled_completely
        order_list_data = self.get_order_book(stock_code)

        if not order_list_data.empty and all(record == trd_side for record in order_list_data['trd_side'].tolist()):
            self.default_logger.info(
                f"{trd_side} Order already sent but not filled yet for {stock_code} with details \n {order_list_data}")
            return True
        return False

    def withdraw_unfilled_orders(self, stock_code, trd_side) -> bool:
        order_list_data = self.get_order_book(stock_code)

        if not order_list_data.empty and any(record == trd_side for record in order_list_data['trd_side'].tolist()):
            self.default_logger.info(
                f"Detected unfilled {trd_side} ORDER for {stock_code}, withdrawal based on new Decision")
            # Iterate all unfilled orders
            for index, row in order_list_data.iterrows():
                self.trade_ctx.modify_order(modify_order_op=ModifyOrderOp.CANCEL, order_id=row['order_id'], qty=0,
                                            price=0, adjust_limit=0, trd_env=self.trd_env, acc_id=self.acc_id)
            return True
        return False

    def place_buy_order(self, stock_code):
        # If already holds position, skip this buy order
        if self.get_holding_position_qty(stock_code) > 0:
            return

        # If Unfilled BUY ORDER is detected, no need to issue another BUY ORDER
        if self.check_unfilled_orders(stock_code, trd_side=TrdSide.BUY):
            return

        # Withdrawal unfilled SELL ORDER if a new BUY DECISION is made
        if self.withdraw_unfilled_orders(stock_code, trd_side=TrdSide.SELL):
            return

        # Get the lot_size and current ask and bid
        lot_size = self.get_market_snapshot(stock_code)['lot_size']
        ask, bid = self.get_ask_and_bid(stock_code)

        # Placing Order
        if self.is_valid_quantity(stock_code, lot_size, ask):
            for retry_count in range(ORDER_RETRY_MAX):
                ret_code, ret_data = self.trade_ctx.place_order(price=ask, qty=lot_size, code=stock_code,
                                                                trd_side=TrdSide.BUY, order_type=OrderType.NORMAL,
                                                                trd_env=self.trd_env, acc_id=self.acc_id)
                if ret_code == RET_OK:
                    self.default_logger.info(
                        f'MAKE BUY ORDER\n\tcode = {stock_code} price = {ask} quantity = {lot_size}')
                    break
                else:
                    self.default_logger.error(f'MAKE BUY ORDER FAILURE, RETRYING {retry_count}...: {ret_data}')
                    time.sleep(0.02)

    def place_sell_order(self, stock_code):
        # If it does not hold any position, skip this sell order
        if self.get_holding_position_qty(stock_code) == 0:
            return

        # If Unfilled SELL ORDER is detected, no need to issue another SELL ORDER
        if self.check_unfilled_orders(stock_code, trd_side=TrdSide.SELL):
            return

        # Withdrawal unfilled Buy ORDER if a new SELL DECISION is made
        if self.withdraw_unfilled_orders(stock_code, trd_side=TrdSide.BUY):
            return

        can_sell_qty = self.get_holding_position(stock_code)

        # 进行清仓
        if can_sell_qty > 0:
            # Get the lot_size and current ask and bid
            ask, bid = self.get_ask_and_bid(stock_code)

            # Place Sell Order with current price and 1 lot size
            for retry_count in range(ORDER_RETRY_MAX):
                ret_code, ret_data = self.trade_ctx.place_order(price=bid, qty=can_sell_qty, code=stock_code,
                                                                trd_side=TrdSide.SELL, order_type=OrderType.NORMAL,
                                                                trd_env=self.trd_env, acc_id=self.acc_id)
                if ret_code == RET_OK:
                    self.default_logger.info(
                        f'MAKE SELL ORDER\n\tcode = {stock_code} price = {bid} quantity = {can_sell_qty}')
                    break
                else:
                    self.default_logger.error(f'MAKE SELL ORDER FAILURE, RETRYING {retry_count}...: {ret_data}')
                    time.sleep(0.02)

    def close_all_positions(self):
        position_data = self.get_holding_position()

        for index, row in position_data.iterrows():
            can_sell_qty = int(row['can_sell_qty'])
            if can_sell_qty == 0:
                continue
            stock_code = row['code']

            if self.trd_env == TrdEnv.REAL:
                # Issue Market-Price Order ONLY SUPPORTED IN TrdEnv.REAL
                ret_code, ret_data = self.trade_ctx.place_order(
                    price=0, qty=can_sell_qty, code=stock_code,
                    trd_side=TrdSide.SELL, order_type=OrderType.MARKET,
                    trd_env=self.trd_env, acc_id=self.acc_id)
            else:
                ask, bid = self.get_ask_and_bid(stock_code)

                ret_code, ret_data = self.trade_ctx.place_order(
                    price=bid, qty=can_sell_qty, code=stock_code,
                    trd_side=TrdSide.SELL, order_type=OrderType.NORMAL,
                    trd_env=self.trd_env, acc_id=self.acc_id)

            if ret_code == RET_OK:
                self.default_logger.info(f'MAKE SELL ORDER\n\tcode = {stock_code} quantity = {can_sell_qty}')
            else:
                self.default_logger.error('MAKE SELL ORDER FAILURE: {}'.format(ret_data))
            time.sleep(2)

    def cancel_all_unfilled_orders(self):
        # Check if an order has already been made but not filled_completely
        ret_code, order_list_data = self.trade_ctx.order_list_query(order_id="",
                                                                    status_filter_list=self.status_filter_list,
                                                                    code='', start='', end='',
                                                                    trd_env=self.trd_env,
                                                                    acc_id=self.acc_id, refresh_cache=False)
        if ret_code != RET_OK:
            self.default_logger.error(f"Cannot acquire order list {order_list_data}")
            return
            # raise Exception('今日订单列表获取异常 {}'.format(market_data))
        for index, row in order_list_data.iterrows():
            ret_code, order_data = self.trade_ctx.modify_order(modify_order_op=ModifyOrderOp.CANCEL,
                                                               order_id=row['order_id'], qty=0,
                                                               price=0, adjust_limit=0, trd_env=self.trd_env, acc_id=0,
                                                               acc_index=0)
            if ret_code != RET_OK:
                self.default_logger.error(f"Cannot Close Positions for Order {row['order_id']} due to {order_data}")
            self.default_logger.info(f"Order {row['order_id']} Cancelled Success. ")
            time.sleep(2)
