#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
import time

from futu import OpenQuoteContext, OpenHKTradeContext, TrdEnv, RET_OK, TrdSide, OrderType, OrderStatus, ModifyOrderOp
from win10toast import ToastNotifier

from util import logger


class TradingUtil:
    def __init__(self, quote_ctx: OpenQuoteContext, trade_ctx: OpenHKTradeContext, trd_env: TrdEnv = TrdEnv.SIMULATE):
        self.default_logger = logger.get_logger('trading_util')
        self.toaster = ToastNotifier()
        self.quote_ctx = quote_ctx
        self.trade_ctx = trade_ctx
        self.trd_env = trd_env
        self.status_filter_list = [OrderStatus.WAITING_SUBMIT,
                                   OrderStatus.SUBMITTING, OrderStatus.SUBMITTED, OrderStatus.FILLED_PART]

    def place_buy_order(self, stock_code):
        ret_code, position_data = self.trade_ctx.position_list_query(code=stock_code, pl_ratio_min=None,
                                                                     pl_ratio_max=None,
                                                                     trd_env=self.trd_env, acc_id=0, acc_index=0,
                                                                     refresh_cache=False)
        if ret_code != RET_OK:
            self.default_logger.error(f"Cannot acquire account position {position_data}")
            return
            # raise Exception('账户信息获取失败: {}'.format(position_data))

        # Already Holds Position of the stock. No need to buy another share
        if not position_data.empty:
            self.default_logger.warn(f"Account holds position for stock {stock_code}")
            return

        # Check if an order has already been made but not filled_completely
        ret_code, order_list_data = self.trade_ctx.order_list_query(order_id="",
                                                                    status_filter_list=self.status_filter_list,
                                                                    code=stock_code, start='', end='',
                                                                    trd_env=self.trd_env,
                                                                    acc_id=0, acc_index=0, refresh_cache=False)
        if ret_code != RET_OK:
            self.default_logger.error(f"Cannot acquire order list {order_list_data}")
            return
            # raise Exception('今日订单列表获取异常 {}'.format(market_data))

        # If Unfilled BUY ORDER is detected, no need to issue another BUY ORDER
        if not order_list_data.empty and all(
                record == TrdSide.BUY for record in order_list_data['trd_side'].tolist()):
            self.default_logger.info(
                f"Order already sent but not filled yet for {stock_code} with details \n {order_list_data}")
            return

        # Withdrawal unfilled sell order if a new BUY DECISION is made
        if not order_list_data.empty and any(
                record == TrdSide.SELL for record in order_list_data['trd_side'].tolist()):
            self.default_logger.info(
                f"Detected unfilled SELL ORDER for {stock_code}, withdrawal based on new Buy Decision")
            # Iterate all unfilled Sell order
            for index, row in order_list_data.iterrows():
                self.trade_ctx.modify_order(modify_order_op=ModifyOrderOp.CANCEL, order_id=row['order_id'], qty=0,
                                            price=0, adjust_limit=0, trd_env=self.trd_env, acc_id=0, acc_index=0)
                return

        # Use Current Market Price / Bid-1 Buy Price to place a buy order
        ret_code, market_data = self.quote_ctx.get_market_snapshot([stock_code])
        if ret_code != RET_OK:
            self.default_logger.error(f"Cannot acquire market snapshot {market_data}")
            return
            # raise Exception('市场快照数据获取异常 {}'.format(market_data))
        cur_price = market_data.iloc[0]['last_price']
        lot_size = market_data.iloc[0]['lot_size']

        ret_code, order_data = self.quote_ctx.get_order_book(stock_code)  # 获取摆盘
        if ret_code != RET_OK:
            self.default_logger.error("can't get orderbook, retrying:{}".format(order_data))
            return
            # raise Exception('摆盘数据获取异常 {}'.format(order_data))
        cur_price = order_data['Bid'][0][0]  # 取得买一价

        # Placing Order
        for i in range(2):
            ret_code, ret_data = self.trade_ctx.place_order(
                price=cur_price,
                qty=lot_size,
                code=stock_code,
                trd_side=TrdSide.BUY,
                order_type=OrderType.NORMAL,
                trd_env=self.trd_env)
            if ret_code == RET_OK:
                self.default_logger.info(
                    f'MAKE BUY ORDER\n\tcode = {stock_code} price = {cur_price} quantity = {lot_size}')
                self.toaster.show_toast("BUY ORDER", f'code = {stock_code} price = {cur_price} quantity = {lot_size}',
                                        icon_path=None, duration=5, threaded=True)
                break
            else:
                self.default_logger.error('MAKE BUY ORDER FAILURE: {}'.format(ret_data))

    def place_sell_order(self, stock_code):
        ret_code, position_data = self.trade_ctx.position_list_query(code=stock_code, pl_ratio_min=None,
                                                                     pl_ratio_max=None,
                                                                     trd_env=self.trd_env, acc_id=0, acc_index=0,
                                                                     refresh_cache=False)
        if ret_code != RET_OK:
            self.default_logger.error(f"Cannot acquire account position {position_data}")
            return
            # raise Exception('账户信息获取失败: {}'.format(position_data))

        # Already Holds No Position of the stock. No need to SELL
        if position_data.empty:
            self.default_logger.warn(f"Account does not hold any position for stock {stock_code}")
            return

        # Check if an order has already been made but not filled_completely
        ret_code, order_list_data = self.trade_ctx.order_list_query(order_id="",
                                                                    status_filter_list=self.status_filter_list,
                                                                    code=stock_code, start='', end='',
                                                                    trd_env=self.trd_env,
                                                                    acc_id=0, acc_index=0, refresh_cache=False)
        if ret_code != RET_OK:
            self.default_logger.error(f"Cannot acquire order list {order_list_data}")
            return
            # raise Exception('今日订单列表获取异常 {}'.format(market_data))

        # If Unfilled SELL ORDER is detected, no need to issue another SELL ORDER
        if not order_list_data.empty and all(
                record == TrdSide.SELL for record in order_list_data['trd_side'].tolist()):
            self.default_logger.info(
                f"Order already sent but not filled yet for {stock_code} with details \n {order_list_data}")
            return

        # Withdrawal unfilled Buy ORDER if a new SELL DECISION is made
        if not order_list_data.empty and any(
                record == TrdSide.BUY for record in order_list_data['trd_side'].tolist()):
            self.default_logger.info(
                f"Detected unfilled BUY ORDER for {stock_code}, withdrawal based on new SELL Decision")
            # Iterate all unfilled Buy order
            for index, row in order_list_data.iterrows():
                self.trade_ctx.modify_order(modify_order_op=ModifyOrderOp.CANCEL, order_id=row['order_id'], qty=0,
                                            price=0, adjust_limit=0, trd_env=self.trd_env, acc_id=0, acc_index=0)
            return

        position_data = position_data.set_index('code')
        can_sell_qty = int(position_data['can_sell_qty'][stock_code])

        # 进行清仓
        if can_sell_qty > 0:
            ret_code, market_data = self.quote_ctx.get_market_snapshot([stock_code])
            if ret_code != RET_OK:
                self.default_logger.error(f"Cannot acquire market snapshot {market_data}")
                return
                # raise Exception('市场快照数据获取异常 {}'.format(market_data))
            cur_price = market_data.iloc[0]['last_price']
            lot_size = market_data.iloc[0]['lot_size']
            if can_sell_qty > lot_size:
                can_sell_qty = lot_size
                self.default_logger.error(f"Can Sell Quantity is larger than Lot Size for stock {stock_code}")

            ret_code, order_data = self.quote_ctx.get_order_book(stock_code)  # 获取摆盘
            if ret_code != RET_OK:
                self.default_logger.error("can't get orderbook, retrying:{}".format(order_data))

            cur_price = order_data['Bid'][0][0]  # 取得买一价

            # Place Sell Order with current price and 1 lot size
            for i in range(2):
                ret_code, ret_data = self.trade_ctx.place_order(
                    price=cur_price,
                    qty=can_sell_qty,
                    code=stock_code,
                    trd_side=TrdSide.SELL,
                    order_type=OrderType.NORMAL,
                    trd_env=self.trd_env)
                if ret_code == RET_OK:
                    self.default_logger.info(
                        f'MAKE SELL ORDER\n\tcode = {stock_code} price = {cur_price} quantity = {can_sell_qty}')
                    self.toaster.show_toast("SELL ORDER",
                                            f'code = {stock_code} price = {cur_price} quantity = {lot_size}',
                                            icon_path=None, duration=5, threaded=True)
                    break
                else:
                    self.default_logger.error('MAKE SELL ORDER FAILURE: {}'.format(ret_data))

    def close_all_positions(self):
        ret_code, position_data = self.trade_ctx.position_list_query(code='', pl_ratio_min=None,
                                                                     pl_ratio_max=None,
                                                                     trd_env=self.trd_env, acc_id=0, acc_index=0,
                                                                     refresh_cache=False)
        if ret_code != RET_OK:
            self.default_logger.error(f"Cannot acquire account position {position_data}")
            return

        for index, row in position_data.iterrows():
            can_sell_qty = int(row['can_sell_qty'])
            if can_sell_qty == 0:
                continue
            stock_code = row['code']

            if self.trd_env == TrdEnv.REAL:
                # Issue Market-Price Order ONLY SUPPORTED IN TrdEnv.REAL
                ret_code, ret_data = self.trade_ctx.place_order(
                    price=0,
                    qty=can_sell_qty,
                    code=stock_code,
                    trd_side=TrdSide.SELL,
                    order_type=OrderType.MARKET,
                    trd_env=self.trd_env)
            else:
                # Get Market Price and ISSUE NORMAL ORDER In TrdEnv.SIMULATE
                ret_code, market_data = self.quote_ctx.get_market_snapshot([stock_code])
                if ret_code != RET_OK:
                    self.default_logger.error(f"Cannot acquire market snapshot {market_data}")
                    return
                    # raise Exception('市场快照数据获取异常 {}'.format(market_data))
                cur_price = market_data.iloc[0]['last_price']
                ret_code, ret_data = self.trade_ctx.place_order(
                    price=cur_price,
                    qty=can_sell_qty,
                    code=stock_code,
                    trd_side=TrdSide.SELL,
                    order_type=OrderType.NORMAL,
                    trd_env=self.trd_env)

            if ret_code == RET_OK:
                self.default_logger.info(
                    'MAKE SELL ORDER code = {} quantity = {} in Market Price'.format(stock_code, can_sell_qty))
            else:
                self.default_logger.error('MAKE SELL ORDER FAILURE: {}'.format(ret_data))
            time.sleep(2)

    def cancel_all_unfilled_orders(self):
        # Check if an order has already been made but not filled_completely
        ret_code, order_list_data = self.trade_ctx.order_list_query(order_id="",
                                                                    status_filter_list=self.status_filter_list,
                                                                    code='', start='', end='',
                                                                    trd_env=self.trd_env,
                                                                    acc_id=0, acc_index=0, refresh_cache=False)
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
