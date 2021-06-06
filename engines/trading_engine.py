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


import datetime
import glob
import itertools
import platform
from datetime import date
from pathlib import Path
import subprocess

from futu import *

from engines import data_engine
from handlers.cur_kline_handler import CurKlineHandler
from handlers.rt_data_handler import RTDataHandler
from handlers.stock_quote_handler import StockQuoteHandler
from util import logger
from util.global_vars import *


class FutuTrade:
    def __init__(self):
        """
            Futu Trading Engine Constructor
        """

        self.config = config
        self.default_logger = logger.get_logger("futu_trade")
        self.__init_futu_client()
        self.quote_ctx = OpenQuoteContext(host=self.config['FutuOpenD.Config'].get('Host'),
                                          port=self.config['FutuOpenD.Config'].getint('Port'))
        self.trade_ctx = OpenHKTradeContext(host=self.config['FutuOpenD.Config'].get('Host'),
                                            port=self.config['FutuOpenD.Config'].getint('Port'))
        self.username = self.config['FutuOpenD.Credential'].get('Username')
        # self.password = self.config['FutuOpenD.Credential'].get('Password')
        self.password_md5 = self.config['FutuOpenD.Credential'].get('Password_md5')
        self.futu_data = data_engine.DatabaseInterface(database_path=self.config['Database'].get('Database_path'))
        self.trd_env = TrdEnv.REAL if self.config.get('FutuOpenD.Config', 'TrdEnv') == 'REAL' else TrdEnv.SIMULATE

        # Futu-Specific Variables
        self.market_list = [Market.HK, Market.US, Market.SH, Market.SZ, Market.HK_FUTURE, Market.SG, Market.JP]
        self.security_type_list = [SecurityType.BOND, SecurityType.BWRT, SecurityType.STOCK, SecurityType.WARRANT,
                                   SecurityType.IDX, SecurityType.ETF, SecurityType.FUTURE, SecurityType.PLATE,
                                   SecurityType.PLATESET]
        self.reference_type_list = [SecurityReferenceType.WARRANT, SecurityReferenceType.FUTURE]

    def __del__(self):
        """
            Default Cleanup Operations for Futu Trade Engine. Disconnect all Quote & Trade Connections
        """
        self.default_logger.info("Deleting Quote_CTX Connection")
        self.quote_ctx.close()  # 关闭当条连接，FutuOpenD会在1分钟后自动取消相应股票相应类型的订阅
        self.default_logger.info("Deleting Trade_CTX Connection")
        self.trade_ctx.close()  # 关闭当条连接，FutuOpenD会在1分钟后自动取消相应股票相应类型的订阅

    def __init_futu_client(self):
        os_type = platform.system()
        if os_type == 'Windows':
            home_dir = str(Path.home())
            opend_dir = f'{home_dir}\AppData\Roaming\Futu\FutuOpenD\FutuOpenD.exe'
            try:
                subprocess.Popen([opend_dir])
            except FileNotFoundError:
                self.default_logger.error("Cannot auto-start FutuOpenD due to missing OpenD client, Ignore.")

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
        Save Historical Data (e.g., 1D, 1W, etc.) from FUTU OpenAPI to ./data folder. Saved in CSV Format
        :param stock_code: Stock Code with Format (e.g., HK.00001)
        :param start_date: Datetime Object that specifies the start date
        :param end_date: Datetime Object that specifies the end date. If left as None, it will be automatically calculated as 365 days after start_date
        :param k_type: FuTu KLType Object
        :return: bool
        """
        out_dir = f'./data/{stock_code}'
        if not os.path.exists(out_dir):
            os.mkdir(out_dir)
        if k_type == KLType.K_DAY:
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
                data.to_csv(output_path, index=False, encoding='utf-8-sig')
                self.default_logger.info(f'Saved: {output_path}')
                # self.__store_data_database(data, k_type=k_type)
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
        """
                获取全局状态

                :return: (ret, data)

                        ret == RET_OK data为包含全局状态的字典，含义如下

                        ret != RET_OK data为错误描述字符串

                        =====================   ===========   ==============================================================
                        key                      value类型                        说明
                        =====================   ===========   ==============================================================
                        market_sz               str            深圳市场状态，参见MarketState
                        market_us               str            美国市场状态，参见MarketState
                        market_sh               str            上海市场状态，参见MarketState
                        market_hk               str            香港市场状态，参见MarketState
                        market_hkfuture         str            香港期货市场状态，参见MarketState
                        market_usfuture         str            美国期货市场状态，参见MarketState
                        server_ver              str            FutuOpenD版本号
                        trd_logined             str            '1'：已登录交易服务器，'0': 未登录交易服务器
                        qot_logined             str            '1'：已登录行情服务器，'0': 未登录行情服务器
                        timestamp               str            Futu后台服务器当前时间戳(秒)
                        local_timestamp         double         FutuOpenD运行机器当前时间戳(
                        =====================   ===========   ==============================================================
        """
        return self.quote_ctx.get_global_state()

    def get_referencestock_list(self, stock_code: str) -> pd.DataFrame:
        """
        获取证券的关联数据
        :param code: 证券id，str，例如HK.00700
        :return: (ret, data)

                ret == RET_OK 返回pd dataframe数据，数据列格式如下

                ret != RET_OK 返回错误字符串
                =======================   ===========   ==============================================================================
                参数                        类型                        说明
                =======================   ===========   ==============================================================================
                code                        str           证券代码
                lot_size                    int           每手数量
                stock_type                  str           证券类型，参见SecurityType
                stock_name                  str           证券名字
                list_time                   str           上市时间（美股默认是美东时间，港股A股默认是北京时间）
                wrt_valid                   bool          是否是窝轮，如果为True，下面wrt开头的字段有效
                wrt_type                    str           窝轮类型，参见WrtType
                wrt_code                    str           所属正股
                future_valid                bool          是否是期货，如果为True，下面future开头的字段有效
                future_main_contract        bool          是否主连合约（期货特有字段）
                future_last_trade_time      string        最后交易时间（期货特有字段，非主连期货合约才有值）
                =======================   ===========   ==============================================================================
        """
        output_df = pd.DataFrame()
        for security_reference_type in self.security_type_list:
            ret, data = self.quote_ctx.get_referencestock_list(stock_code, security_reference_type)
            if ret == RET_OK:
                self.default_logger.info(f"Received Reference Stock List for {stock_code}")
                output_df = pd.concat([output_df, data], ignore_index=True)
            else:
                self.default_logger.error(f"Cannot Retrieve Reference Stock List for {stock_code}")
        return output_df

    def get_filtered_turnover_stocks(self) -> list:
        """
        A quick way to get all stocks with at least 100 million HKD turnover and a stock price >= 1 HKD
        :return:
        """
        simple_filter = SimpleFilter()
        simple_filter.filter_min = 1
        simple_filter.stock_field = StockField.CUR_PRICE
        simple_filter.is_no_filter = False
        financial_filter = AccumulateFilter()
        financial_filter.filter_min = 100000000
        financial_filter.stock_field = StockField.TURNOVER
        financial_filter.is_no_filter = False
        financial_filter.sort = SortDir.ASCEND
        financial_filter.days = 10
        begin_index = 0
        output_list = []

        while True:
            ret, ls = self.quote_ctx.get_stock_filter(market=Market.HK, filter_list=[simple_filter, financial_filter],
                                                      begin=begin_index)  # 对香港市场的股票做简单和财务筛选
            if ret == RET_OK:
                last_page, all_count, ret_list = ls
                output_list.extend([item.stock_code for item in ret_list])
                begin_index += 200
                if begin_index >= all_count:
                    break
            elif ret == RET_ERROR:
                return []

        return output_list

    def get_account_info(self) -> dict:
        """
        Query fund data such as net asset value, securities market value, cash, and purchasing power of trading accounts.
        :return: dictionary for UI Info
        """

        self.__unlock_trade()

        ret, data = self.trade_ctx.accinfo_query(trd_env=self.trd_env, acc_id=0, acc_index=0, refresh_cache=False,
                                                 currency=Currency.HKD)
        if ret == RET_OK:
            self.default_logger.info(f"Received Account Info for Environment: {self.trd_env}")
            # Retrieve the first row as the default account
            data = data.iloc[0]
            account_info = {
                "Net Assets":         data["total_assets"],
                "P/L":                data["realized_pl"],
                "Securities Value":   data["market_val"],
                "Cash":               data["cash"],
                "Buying Power":       data["power"],
                "Short Sell Power":   data["max_power_short"],
                "LMV":                data["long_mv"],
                "SMV":                data["short_mv"],
                "Available Balance":  data["avl_withdrawal_cash"],
                "Maximum Withdrawal": data["max_withdrawal"]
            }
            return {index: str(item) for index, item in account_info.items()}
        else:
            self.default_logger.error(f"Cannot Retrieve Account Info for {self.trd_env}")

    def get_data_realtime(self, stock_list: list, sub_type: SubType = SubType.K_1M, kline_num: int = 1000) -> dict:
        """
        Receive real-time K-Line data as initial technical indicators observations
        注意：len(code_list) * 订阅的K线类型的数量 <= 100
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
        column_names = json.loads(self.config.get('FutuOpenD.DataFormat', 'HistoryDataFormat'))
        history_df = pd.DataFrame(columns=column_names)
        # If force update, update all 2-years 1M data. Otherwise only update the last week's data
        start_date = str((datetime.today() - timedelta(days=round(365 * years))).date()) if force_update else str(
            (datetime.today() - timedelta(days=30)).date())
        end_date = str(datetime.today().date())
        # This will give a list of dates between 2-years range
        date_range = pd.date_range(start_date, end_date, freq='d').strftime("%Y-%m-%d").tolist()
        # Retrieve the first page
        ret, data, page_req_key = self.quote_ctx.request_history_kline(stock_code,
                                                                       start=start_date,
                                                                       end=end_date,
                                                                       ktype=KLType.K_1M, autype=AuType.QFQ,
                                                                       fields=[KL_FIELD.ALL],
                                                                       max_count=1000, page_req_key=None,
                                                                       extended_time=False)
        if ret == RET_OK:
            history_df = pd.concat([history_df, data], ignore_index=True)
        else:
            self.default_logger.error(f'Cannot get Historical K-line data: {data}')
            return

        # 请求后面的所有结果
        while page_req_key is not None:
            # The inner loop is to ensure that whenever there is an error, we can re-try until it success
            while True:
                original_page_req_key = page_req_key
                ret, data, page_req_key = self.quote_ctx.request_history_kline(stock_code,
                                                                               start=start_date,
                                                                               end=end_date,
                                                                               ktype=KLType.K_1M, autype=AuType.QFQ,
                                                                               fields=[KL_FIELD.ALL],
                                                                               max_count=1000,
                                                                               page_req_key=page_req_key,
                                                                               extended_time=False)
                if ret == RET_OK:
                    history_df = pd.concat([history_df, data], ignore_index=True)
                    break
                else:
                    self.default_logger.error(f'Cannot get Historical K-line data: {data}')
                    # Revert back to previous page req key and re-try again
                    page_req_key = original_page_req_key
                    time.sleep(1)

        for input_date in date_range:
            output_path = f'./data/{stock_code}/{stock_code}_{input_date}_1M.csv'
            output_df = history_df[history_df['time_key'].str.contains(input_date)]
            output_df.to_csv(output_path, index=False, encoding='utf-8-sig')
            self.default_logger.info(f'Saved: {output_path}')
            # self.__store_data_database(output_df, k_type=KLType.K_1M)

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

    def update_owner_plate(self, stock_list: list):
        """
        Update Owner Plate information for all equities in Hong Kong Kong stock market.
        :param stock_list: A list of all equities (i.e., stock code)
        """
        # Slice the list into 200-elements per list
        stock_lists = [stock_list[i:i + 200] for i in range(0, len(stock_list), 200)]
        output_df = pd.DataFrame()
        for stock_list in stock_lists:
            ret, data = self.quote_ctx.get_owner_plate(stock_list)
            if ret == RET_OK:
                output_df = pd.concat([output_df, data], ignore_index=True)
            else:
                self.default_logger.error(f'Cannot get Owner Plate: {data}')
            time.sleep(3.5)
        output_path = './data/Stock_Pool/stock_owner_plate.csv'
        output_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        self.default_logger.info(f'Stock Owner Plate Updated: {output_path}')

    def update_stock_basicinfo(self):
        """
        Update stock static information for all markets and all forms of equities (E.g., Stock, Futures, etc.)
        """
        output_df = pd.DataFrame()
        for market, stock_type in itertools.product(self.market_list, self.security_type_list):
            ret, data = self.quote_ctx.get_stock_basicinfo(market=market, stock_type=stock_type)
            if ret == RET_OK:
                output_df = pd.concat([output_df, data], ignore_index=True)
            else:
                self.default_logger.error(f'Cannot get Stock Basic Info: {data}')
        output_path = './data/Stock_Pool/stock_basic_info.csv'
        output_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        self.default_logger.info(f'Stock Static Basic Info Updated: {output_path}')

    def store_all_data_database(self):
        """
        Store all files in ./data/{stock_code}/*.csv to the database in pre-defined format.
        """
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

    def stock_quote_subscription(self, input_data: dict, stock_list: list, strategy_map: dict, timeout: int = 60):
        """
            实时报价回调，异步处理已订阅股票的实时报价推送。
        :param input_data: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :param strategy_map: Strategies defined in ./strategies class. Should be inherited from based class Strategies
        :param timeout: Subscription Timeout in secs.
        """
        self.__unlock_trade()

        # Stock Quote Handler
        handler = StockQuoteHandler(quote_ctx=self.quote_ctx, trade_ctx=self.trade_ctx, input_data=input_data,
                                    strategy_map=strategy_map, trd_env=self.trd_env)
        self.quote_ctx.set_handler(handler)  # 设置实时报价回调
        self.quote_ctx.subscribe(stock_list, [SubType.QUOTE, SubType.ORDER_BOOK, SubType.BROKER], is_first_push=True,
                                 subscribe_push=True)  # 订阅实时报价类型，FutuOpenD开始持续收到服务器的推送
        time.sleep(timeout)

    def rt_data_subscription(self, input_data: dict, stock_list: list, strategy_map: dict, timeout: int = 60):
        """
            实时分时回调，异步处理已订阅股票的实时分时推送。
        :param input_data: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :param strategy_map: Strategies defined in ./strategies class. Should be inherited from based class Strategies
        :param timeout: Subscription Timeout in secs.
        """
        self.__unlock_trade()

        # RT Data Handler
        handler = RTDataHandler(quote_ctx=self.quote_ctx, trade_ctx=self.trade_ctx, input_data=input_data,
                                strategy_map=strategy_map, trd_env=self.trd_env)
        self.quote_ctx.set_handler(handler)  # 设置实时分时推送回调
        self.quote_ctx.subscribe(stock_list, [SubType.RT_DATA, SubType.ORDER_BOOK, SubType.BROKER], is_first_push=True,
                                 subscribe_push=True)  # 订阅分时类型，FutuOpenD开始持续收到服务器的推送
        time.sleep(timeout)

    def cur_kline_subscription(self, input_data: dict, stock_list: list, strategy_map: dict, timeout: int = 60,
                               subtype: SubType = SubType.K_1M):
        """
            实时 K 线回调，异步处理已订阅股票的实时 K 线推送。
        :param input_data: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :param strategy_map: Strategies defined in ./strategies class. Should be inherited from based class Strategies
        :param timeout: Subscription Timeout in secs.
        :param subtype: Subscription SubType for FuTu (i.e., Trading Frequency)

        """
        self.__unlock_trade()

        # cur Kline Handler
        handler = CurKlineHandler(quote_ctx=self.quote_ctx, trade_ctx=self.trade_ctx, input_data=input_data,
                                  strategy_map=strategy_map, trd_env=self.trd_env)
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

    def request_trading_days(self, start_date: str, end_date: str) -> dict:
        """
        请求交易日，注意该交易日是通过自然日剔除周末和节假日得到，未剔除临时休市数据。
        :param start_date:
        :param end_date:
        :return: [{'time': '2020-04-01', 'trade_date_type': 'WHOLE'}, ...]
        """
        ret, data = self.quote_ctx.request_trading_days(TradeDateMarket.HK, start=start_date, end=end_date)
        if ret == RET_OK:
            self.default_logger.info(f'Trading Days: {data}')
            return data
        else:
            self.default_logger.error(f'error: {data}')
