#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2021

import configparser
import datetime
import glob
from datetime import date
from pathlib import Path

from futu import *

import data_engine
import logger
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


class FutuTrade:
    def __init__(self):
        """
            Futu Trading Engine Constructor
        """
        self.config = configparser.ConfigParser()
        self.config.read("config.ini")
        self.quote_ctx = OpenQuoteContext(host=self.config['FutuOpenD.Config'].get('Host'),
                                          port=self.config['FutuOpenD.Config'].getint('Port'))
        self.trade_ctx = OpenHKTradeContext(host=self.config['FutuOpenD.Config'].get('Host'),
                                            port=self.config['FutuOpenD.Config'].getint('Port'))
        self.username = self.config['FutuOpenD.Credential'].get('Username')
        self.password = self.config['FutuOpenD.Credential'].get('Password')
        self.password_md5 = self.config['FutuOpenD.Credential'].get('Password_md5')
        self.futu_data = data_engine.DatabaseInterface(database_path=self.config['Database'].get('Database_path'))
        self.default_logger = logger.get_logger("futu_trade")
        self.trd_env = TrdEnv.REAL if self.config.get('FutuOpenD.Config', 'TrdEnv') == 'REAL' else TrdEnv.SIMULATE

    def __del__(self):
        """
            Default Cleanup Operations for Futu Trade Engine. Disconnect all Quote & Trade Connections
        """
        self.default_logger.info("Deleting Quote_CTX Connection")
        self.quote_ctx.close()  # 关闭当条连接，FutuOpenD会在1分钟后自动取消相应股票相应类型的订阅
        self.default_logger.info("Deleting Trade_CTX Connection")
        self.trade_ctx.close()  # 关闭当条连接，FutuOpenD会在1分钟后自动取消相应股票相应类型的订阅

    def get_market_state(self):
        return self.quote_ctx.get_global_state()

    def __save_historical_data(self, stock_code: str, start_date: date, end_date: date = None,
                               k_type: object = KLType) -> bool:
        """
        Save Historical Data (e.g., 1M, 15M, 1D, etc.) from FUTU OpenAPI to ./data folder. Saved in CSV Format
        :param stock_code: Stock Code with Format (e.g., HK.00001)
        :param start_date: Datetime Object that specifies the start date
        :param end_date: Datetime Object that specifies the end date. If left as None, it will be automatically calculated as 365 days after start_date
        :param k_type: FuTu KLType Object
        :return: bool
        """
        out_dir = f'./data/{stock_code}'
        if not os.path.exists(out_dir):
            os.mkdir(out_dir)
        if k_type == KLType.K_1M:
            output_path = f'./data/{stock_code}/{stock_code}_{start_date.strftime("%Y-%m-%d")}_1M.csv'
        elif k_type == KLType.K_DAY:
            output_path = f'./data/{stock_code}/{stock_code}_{start_date.year}_1D.csv'
        else:
            self.default_logger.error(f'Unsupported KLType. Please try it later.')
            return False

        # Ensure update current day's 1M data & current year's 1D data
        if os.path.exists(output_path) and ((start_date != datetime.today().date() and k_type == KLType.K_1M) or (
                start_date.year != datetime.today().date().year and k_type == KLType.K_DAY)):
            return False

        # Request Historical K-line Data (Daily)
        start_date = start_date.strftime("%Y-%m-%d")
        end_date = end_date.strftime("%Y-%m-%d") if end_date is not None else None
        while True:
            ret, data, page_req_key = self.quote_ctx.request_history_kline(stock_code, start=start_date,
                                                                           end=end_date,
                                                                           ktype=k_type, autype=AuType.QFQ,
                                                                           fields=[KL_FIELD.ALL],
                                                                           max_count=1000, page_req_key=None,
                                                                           extended_time=False)
            if ret == RET_OK:
                data.to_csv(output_path, index=False)
                self.default_logger.info(f'Saved: {output_path}')
                for index, row in data.iterrows():
                    self.futu_data.add_stock_data(row['code'], row['time_key'], row['open'], row['close'], row['high'],
                                                  row['low'], row['pe_ratio'], row['turnover_rate'], row['volume'],
                                                  row['turnover'], row['change_rate'], row['last_close'], k_type)
                return True
            else:
                # Retry Storing Data due to too frequent requests (max. 60 requests per 30 seconds)
                time.sleep(1)
                self.default_logger.error(f'Historical Data Store Error: {data}')

    def store_all_data_database(self):
        file_list = glob.glob(f"./data/*/*_1M.csv", recursive=True)
        for input_file in file_list:
            input_csv = pd.read_csv(input_file, index_col=None)
            self.default_logger.info(f'Processing: {input_file}')
            for index, row in input_csv.iterrows():
                self.futu_data.add_stock_data(row['code'], row['time_key'], row['open'], row['close'], row['high'],
                                              row['low'], row['pe_ratio'], row['turnover_rate'], row['volume'],
                                              row['turnover'], row['change_rate'], row['last_close'], KLType.K_1M)
            self.futu_data.commit()

        file_list = glob.glob(f"./data/*/*_1D.csv", recursive=True)
        for input_file in file_list:
            input_csv = pd.read_csv(input_file, index_col=None)
            self.default_logger.info(f'Processing: {input_file}')
            for index, row in input_csv.iterrows():
                self.futu_data.add_stock_data(row['code'], row['time_key'], row['open'], row['close'], row['high'],
                                              row['low'], row['pe_ratio'], row['turnover_rate'], row['volume'],
                                              row['turnover'], row['change_rate'], row['last_close'], KLType.K_DAY)
            self.futu_data.commit()

    def update_1M_data(self, stock_code: str, years: int = 2) -> None:
        """
            Update 1M Data to ./data/{stock_code} folders for max. 2-years duration
        :param stock_code: Stock Code with Format (e.g., HK.00001)
        :param years: 2 years
        """
        for i in range(365 * years):
            day = datetime.today() - timedelta(days=i)
            if not self.__save_historical_data(stock_code, day.date(), day.date(),
                                               KLType.K_1M):
                continue
            time.sleep(0.7)

    def update_1D_data(self, stock_code: str, years: int = 10) -> None:
        """
            Update 1D Data (365 days per file) to ./data/{stock_code} folders for max. 2-years duration
        :param stock_code: Stock Code with Format (e.g., HK.00001)
        :param years: 10 years
        """
        for i in range(0, years + 1):
            day = date((datetime.today() - timedelta(days=i * 365)).year, 1, 1)
            if not self.__save_historical_data(stock_code=stock_code, start_date=day,
                                               k_type=KLType.K_DAY):
                continue
            time.sleep(0.7)

    def get_1M_data(self, stock_list: list):
        """
            Get 1M Data from CSV based on Stock List. Returned in Dict format
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :return: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        """
        # Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        input_data = {}
        for stock_code in stock_list:
            delta = 0
            # Check if the file already exists or the dataframe has no data (Non-Trading Day)
            while \
                    not Path(
                        f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv').exists() or pd.read_csv(
                        f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv').empty:
                delta += 1

            output_path = f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv'
            input_csv = pd.read_csv(output_path, index_col=None)
            self.default_logger.info(f'Get {output_path} Success from Stock List Success.')
            input_data[stock_code] = input_data.get(stock_code, input_csv)
        return input_data

    def stock_price_subscription(self, input_data: dict, stock_list: list, strategy: Strategies, timeout: int = 60):
        """

        :param input_data: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :param strategy: Strategies defined in ./strategies class. Should be inherited from based class Strategies
        :param timeout: Subscription Timeout in secs.
        """

        # Unlock Trading Account if TrdEnv.REAL
        if self.trd_env == TrdEnv.REAL:
            ret, data = self.trade_ctx.unlock_trade(self.password)
            if ret == RET_OK:
                self.default_logger.info("Account Unlock Success.")
            else:
                raise Exception("Account Unlock Unsuccessful: {}".format(data))

        # Stock Quote Handler
        handler = StockQuoteHandler(quote_ctx=self.quote_ctx, trade_ctx=self.trade_ctx, input_data=input_data,
                                    strategy=strategy, trd_env=self.trd_env)
        self.quote_ctx.set_handler(handler)  # 设置实时报价回调
        self.quote_ctx.subscribe(stock_list, [SubType.QUOTE], is_first_push=True,
                                 subscribe_push=True)  # 订阅实时报价类型，FutuOpenD开始持续收到服务器的推送
        time.sleep(timeout)  # 设置脚本接收FutuOpenD的推送持续时间为60秒

    def display_quota(self):
        ret, data = self.quote_ctx.query_subscription()
        if ret == RET_OK:
            self.default_logger.info(f'Query Subscription Quota: {data}')
        ret, data = self.quote_ctx.get_history_kl_quota(get_detail=True)
        if ret == RET_OK:
            self.default_logger.info(f'Historical K-line Quota: {data}')


def update_hsi_constituents(input_path='./data/HSI.Constituents'):
    file_list = glob.glob(f"{input_path}/*.xlsx")
    hsi_constituents = []
    for input_file in file_list:
        hsi_constituents = pd.read_excel(input_file, index_col=0, engine='openpyxl')
        hsi_constituents = hsi_constituents.iloc[1::2].index.tolist()
        hsi_constituents = ['.'.join(item.split('.')[::-1]) for item in hsi_constituents]
    with open(f'./data/HSI.Constituents/HSI_constituents_{datetime.today().date()}.json', 'w+') as file_obj:
        json.dump(list(set(hsi_constituents)), file_obj)


def update_customized_stocks(input_path='./data/Customized', input_list=None):
    # Need to get existing stocks in the JSON and append it
    file_list = glob.glob(f"{input_path}/*.xlsx")
    stock_list = [] if input_list is None else input_list
    for input_file in file_list:
        customized_stocks = pd.read_excel(input_file, index_col=0, engine='openpyxl')
        customized_stocks = customized_stocks.iloc[1::2].index.tolist()
        stock_list.extend(['.'.join(item.split('.')[::-1]) for item in customized_stocks])
    with open(f'./data/Customized/Customized_Stocks_{datetime.today().date()}.json', 'w+') as file_obj:
        json.dump(list(set(stock_list)), file_obj)


def get_hsi_constituents(input_file):
    with open(input_file, 'r') as file_obj:
        return json.load(file_obj)


def get_customized_stocks(input_file):
    with open(input_file, 'r') as file_obj:
        return json.load(file_obj)
