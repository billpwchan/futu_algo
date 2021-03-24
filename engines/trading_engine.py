#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import configparser
import datetime
import glob
from datetime import date
from pathlib import Path

from futu import *

from engines import data_engine
from handlers.cur_kline_handler import CurKlineHandler
from handlers.rt_data_handler import RTDataHandler
from handlers.stock_quote_handler import StockQuoteHandler
from strategies.Strategies import Strategies
from util import logger


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
        # self.password = self.config['FutuOpenD.Credential'].get('Password')
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

    def __unlock_trade(self):
        """
        Unlock Trading Account if TrdEnv.REAL
        """
        if self.trd_env == TrdEnv.REAL:
            ret, data = self.trade_ctx.unlock_trade(password_md5=self.password_md5)
            if ret == RET_OK:
                self.default_logger.info("Account Unlock Success.")
            else:
                raise Exception("Account Unlock Unsuccessful: {}".format(data))

    def __save_historical_data(self, stock_code: str, start_date: date, end_date: date = None,
                               k_type: object = KLType, force_update: bool = False) -> bool:
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
        elif k_type == KLType.K_WEEK:
            output_path = f'./data/{stock_code}/{stock_code}_{start_date.year}_1W.csv'
        else:
            self.default_logger.error(f'Unsupported KLType. Please try it later.')
            return False

        # Ensure update current day's 1M data & current year's 1D data
        if os.path.exists(output_path) and not force_update and (
                (start_date != datetime.today().date() and k_type == KLType.K_1M) or
                (start_date.year != datetime.today().date().year and (
                        k_type == KLType.K_DAY or k_type == KLType.K_WEEK))
        ):
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
                self.__store_data_database(data, k_type=k_type)
                return True
            else:
                # Retry Storing Data due to too frequent requests (max. 60 requests per 30 seconds)
                time.sleep(1)
                self.default_logger.error(f'Historical Data Store Error: {data}')

    def __store_data_database(self, data, k_type):
        for index, row in data.iterrows():
            self.futu_data.add_stock_data(row['code'], row['time_key'], row['open'], row['close'], row['high'],
                                          row['low'], row['pe_ratio'], row['turnover_rate'], row['volume'],
                                          row['turnover'], row['change_rate'], row['last_close'], k_type)
        self.futu_data.commit()

    def get_market_state(self):
        return self.quote_ctx.get_global_state()

    def get_1M_data(self, stock_list: list) -> dict:
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

            input_path = f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv'
            input_csv = pd.read_csv(input_path, index_col=None)
            self.default_logger.info(f'Get {input_path} Success from Stock List Success.')
            input_data[stock_code] = input_data.get(stock_code, input_csv)
        return input_data

    def get_data_realtime(self, stock_list: list, sub_type: SubType = SubType.K_1M, kline_num: int = 1000) -> dict:
        """
        Receive real-time K-Line data as initial technical indicators observations
        :param stock_list: List of selected stocks ['HK.00009', 'HK.00001']
        :param sub_type: Futu subscription type
        :param kline_num: Number of observations (i.e., default to 100)
        :return: dictionary of k-line data
        """
        input_data = {}
        ret_sub, err_message = self.quote_ctx.subscribe(stock_list, [sub_type], subscribe_push=False)
        for stock_code in stock_list:
            if ret_sub == RET_OK:  # 订阅成功
                ret, data = self.quote_ctx.get_cur_kline(stock_code, kline_num, sub_type, AuType.QFQ)
                if ret == RET_OK:
                    input_data[stock_code] = input_data.get(stock_code, data)
                else:
                    self.default_logger.error(f'Cannot get Real-time K-line data: {data}')
        return input_data

    def update_1M_data(self, stock_code: str, years=2, force_update: bool = False) -> None:
        """
            Update 1M Data to ./data/{stock_code} folders for max. 2-years duration
        :param force_update:
        :param stock_code: Stock Code with Format (e.g., HK.00001)
        :param years: 2 years
        """
        for i in range(round(365 * years)):
            day = datetime.today() - timedelta(days=i)
            if not self.__save_historical_data(stock_code=stock_code, start_date=day.date(), end_date=day.date(),
                                               k_type=KLType.K_1M, force_update=force_update):
                continue
            time.sleep(0.6)

    def update_DW_data(self, stock_code: str, years=10, force_update: bool = False,
                       k_type: KLType = KLType.K_DAY) -> None:
        """
            Update 1D Data (365 days per file) to ./data/{stock_code} folders for max. 2-years duration
        :param force_update:
        :param stock_code: Stock Code with Format (e.g., HK.00001)
        :param years: 10 years
        :param k_type: Futu K-Line Type
        """
        for i in range(0, round(years + 1)):
            day = date((datetime.today() - timedelta(days=i * 365)).year, 1, 1)
            if not self.__save_historical_data(stock_code=stock_code, start_date=day,
                                               k_type=k_type, force_update=force_update):
                continue
            time.sleep(0.6)

    def store_all_data_database(self):
        file_list = glob.glob(f"./data/*/*_1M.csv", recursive=True)
        for input_file in file_list:
            input_csv = pd.read_csv(input_file, index_col=None)
            self.default_logger.info(f'Saving to Database: {input_file}')
            self.__store_data_database(input_csv, k_type=KLType.K_1M)

        file_list = glob.glob(f"./data/*/*_1D.csv", recursive=True)
        for input_file in file_list:
            input_csv = pd.read_csv(input_file, index_col=None)
            self.default_logger.info(f'Saving to Database: {input_file}')
            self.__store_data_database(input_csv, k_type=KLType.K_DAY)

        file_list = glob.glob(f"./data/*/*_1W.csv", recursive=True)
        for input_file in file_list:
            input_csv = pd.read_csv(input_file, index_col=None)
            self.default_logger.info(f'Saving to Database: {input_file}')
            self.__store_data_database(input_csv, k_type=KLType.K_WEEK)

    def stock_quote_subscription(self, input_data: dict, stock_list: list, strategy: Strategies, timeout: int = 60):
        """
            实时报价回调，异步处理已订阅股票的实时报价推送。
        :param input_data: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :param strategy: Strategies defined in ./strategies class. Should be inherited from based class Strategies
        :param timeout: Subscription Timeout in secs.
        """
        self.__unlock_trade()

        # Stock Quote Handler
        handler = StockQuoteHandler(quote_ctx=self.quote_ctx, trade_ctx=self.trade_ctx, input_data=input_data,
                                    strategy=strategy, trd_env=self.trd_env)
        self.quote_ctx.set_handler(handler)  # 设置实时报价回调
        self.quote_ctx.subscribe(stock_list, [SubType.QUOTE, SubType.ORDER_BOOK, SubType.BROKER], is_first_push=True,
                                 subscribe_push=True)  # 订阅实时报价类型，FutuOpenD开始持续收到服务器的推送
        time.sleep(timeout)

    def rt_data_subscription(self, input_data: dict, stock_list: list, strategy: Strategies, timeout: int = 60):
        """
            实时分时回调，异步处理已订阅股票的实时分时推送。
        :param input_data: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :param strategy: Strategies defined in ./strategies class. Should be inherited from based class Strategies
        :param timeout: Subscription Timeout in secs.
        """
        self.__unlock_trade()

        # RT Data Handler
        handler = RTDataHandler(quote_ctx=self.quote_ctx, trade_ctx=self.trade_ctx, input_data=input_data,
                                strategy=strategy, trd_env=self.trd_env)
        self.quote_ctx.set_handler(handler)  # 设置实时分时推送回调
        self.quote_ctx.subscribe(stock_list, [SubType.RT_DATA, SubType.ORDER_BOOK, SubType.BROKER], is_first_push=True,
                                 subscribe_push=True)  # 订阅分时类型，FutuOpenD开始持续收到服务器的推送
        time.sleep(timeout)

    def cur_kline_subscription(self, input_data: dict, stock_list: list, strategy: Strategies, timeout: int = 60,
                               subtype: SubType = SubType.K_1M):
        """
            实时 K 线回调，异步处理已订阅股票的实时 K 线推送。
        :param input_data: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :param strategy: Strategies defined in ./strategies class. Should be inherited from based class Strategies
        :param timeout: Subscription Timeout in secs.
        :param subtype: Subscription SubType for FuTu (i.e., Trading Frequency)

        """
        self.__unlock_trade()

        # cur Kline Handler
        handler = CurKlineHandler(quote_ctx=self.quote_ctx, trade_ctx=self.trade_ctx, input_data=input_data,
                                  strategy=strategy, trd_env=self.trd_env)
        self.quote_ctx.set_handler(handler)  # 设置实时分时推送回调
        self.quote_ctx.subscribe(stock_list, [subtype, SubType.ORDER_BOOK, SubType.BROKER], is_first_push=True,
                                 subscribe_push=True)  # 订阅K线数据类型，FutuOpenD开始持续收到服务器的推送
        time.sleep(timeout)

    def display_quota(self):
        """
            Display Stock Subscription & Historical K-Line Quota
        """
        ret, data = self.quote_ctx.query_subscription()
        if ret == RET_OK:
            self.default_logger.info(f'Query Subscription Quota: \n{data}')
        ret, data = self.quote_ctx.get_history_kl_quota(get_detail=True)
        if ret == RET_OK:
            self.default_logger.info(f'Historical K-line Quota: \n{data}')
