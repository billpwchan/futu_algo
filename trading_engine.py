#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import configparser
import datetime
import glob
from datetime import date
from pathlib import Path

from futu import *

import logger
from strategies.MACDCross import MACDCross
from strategies.Strategies import Strategies


class StockQuoteHandler(StockQuoteHandlerBase):
    def __init__(self, input_data: dict, strategy: Strategies):
        self.config = configparser.ConfigParser()
        self.config.read("config.ini")
        self.default_logger = logger.get_logger('stock_quote')
        self.input_data = input_data
        self.strategy = strategy
        super().__init__()

    def on_recv_rsp(self, rsp_str):
        ret_code, data = super(StockQuoteHandler, self).on_recv_rsp(rsp_str)
        if ret_code != RET_OK:
            self.default_logger.error("StockQuoteTest: error, msg: %s" % data)
            return RET_ERROR, data
        # MACD Crossover Logic PoC
        self.default_logger.info("Subscribed!")
        # Column Mapping between Subscribed Data <==> Historical Data
        data['time_key'] = data['data_date'] + ' ' + data['data_time']
        data = data[
            ['code', 'time_key', 'open_price', 'last_price', 'high_price', 'low_price', 'amplitude',
             'turnover_rate', 'volume', 'turnover', 'amplitude', 'prev_close_price']]
        data.columns = json.loads(self.config.get('FutuOpenD.DataFormat', 'HistoryDataFormat'))

        # Update Latest Data to the Strategy before Buy/Sell
        self.strategy.parse_data(data)

        return RET_OK, data


class FutuTrade():
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read("config.ini")
        self.quote_ctx = OpenQuoteContext(host=self.config['FutuOpenD.Config'].get('Host'),
                                          port=self.config['FutuOpenD.Config'].getint('Port'))
        # Initialize Subscription Logic

        self.default_logger = logger.get_logger("futu_trade")

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.quote_ctx.close()  # 关闭当条连接，FutuOpenD会在1分钟后自动取消相应股票相应类型的订阅

    def __del__(self):
        self.quote_ctx.close()  # 关闭当条连接，FutuOpenD会在1分钟后自动取消相应股票相应类型的订阅

    def get_market_state(self):
        return self.quote_ctx.get_global_state()

    def save_historical_data(self, stock_code: str, start_date: date, end_date: date = None,
                             k_type: object = KLType) -> None:
        """
        Save Historical Data (e.g., 1M, 15M, 1D, etc.) from FUTU OpenAPI to ./data folder. Saved in CSV Format
        :param stock_code: Stock Code with Format (e.g., HK.00001)
        :param start_date: Datetime Object that specifies the start date
        :param end_date: Datetime Object that specifies the end date. If left as None, it will be automatically calculated as 365 days after start_date
        :param k_type: FuTu KLType Object
        :return: None
        """
        out_dir = f'./data/{stock_code}'
        if not os.path.exists(out_dir):
            os.mkdir(out_dir)
        if k_type == KLType.K_1M:
            output_path = f'./data/{stock_code}/{stock_code}_{start_date.strftime("%Y-%m-%d")}_1M.csv'
        elif k_type == KLType.K_DAY:
            output_path = f'./data/{stock_code}/{stock_code}_{start_date.year}_1D.csv'

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
                return True
            else:
                time.sleep(1)
                self.default_logger.error(f'Historical Data Store Error: {data}')

    def update_1M_data(self, stock_code, years=2):
        for i in range(365 * years):
            day = datetime.today() - timedelta(days=i)
            if not self.save_historical_data(stock_code, day.date(), day.date(),
                                             KLType.K_1M):
                continue
            time.sleep(0.7)

    def update_1D_data(self, stock_code, years=10):
        for i in range(0, years + 1):
            day = date((datetime.today() - timedelta(days=i * 365)).year, 1, 1)
            if not self.save_historical_data(stock_code=stock_code, start_date=day,
                                             k_type=KLType.K_DAY):
                continue
            time.sleep(0.7)

    def stock_price_subscription(self, stock_list) -> bool:
        input_data = {}
        for stock_code in stock_list:
            delta = 0
            while \
                    not Path(
                        f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv').exists() \
                            or pd.read_csv(
                        f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv').empty:
                delta += 1
            if delta > 1:
                self.default_logger.error(
                    "Subscription Failed: Outdated Data. Please use update_{time_period}_data function to update")
                return False
            output_path = f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv'
            input_csv = pd.read_csv(output_path, index_col=None)
            self.default_logger.debug(input_csv.empty)
            input_data[stock_code] = input_data.get(stock_code, input_csv)

        self.default_logger.debug(f'Input Data: {input_data}')
        # Initialize Strategy - MACD as an Example
        macd_cross = MACDCross(input_data=input_data)
        handler = StockQuoteHandler(input_data, macd_cross)

        self.quote_ctx.set_handler(handler)  # 设置实时报价回调
        self.quote_ctx.subscribe(stock_list, [SubType.QUOTE], is_first_push=True,
                                 subscribe_push=True)  # 订阅实时报价类型，FutuOpenD开始持续收到服务器的推送
        time.sleep(60)  # 设置脚本接收FutuOpenD的推送持续时间为60秒


def display_result(ret, data):
    if ret == RET_OK:
        print(data)
    else:
        print('error:', data)


def update_hsi_constituents(input_path='./data/HSI.Constituents'):
    file_list = glob.glob(f"{input_path}/*.xlsx")
    hsi_constituents = []
    for input_file in file_list:
        hsi_constituents = pd.read_excel(input_file, index_col=0, engine='openpyxl')
        hsi_constituents = hsi_constituents.iloc[1::2].index.tolist()
        hsi_constituents = ['.'.join(item.split('.')[::-1]) for item in hsi_constituents]
    with open(f'./data/HSI.Constituents/HSI_constituents_{datetime.today().date()}.json', 'w+') as f:
        json.dump(list(set(hsi_constituents)), f)


def update_customized_stocks(input_path='./data/Customized', input_list=None):
    file_list = glob.glob(f"{input_path}/*.xlsx")
    stock_list = [] if input_list is None else input_list
    for input_file in file_list:
        customized_stocks = pd.read_excel(input_file, index_col=0, engine='openpyxl')
        customized_stocks = customized_stocks.iloc[1::2].index.tolist()
        stock_list.extend(['.'.join(item.split('.')[::-1]) for item in customized_stocks])
    with open(f'./data/Customized/Customized_Stocks_{datetime.today().date()}.json', 'w+') as f:
        json.dump(list(set(stock_list)), f)


def get_hsi_constituents(input_file):
    with open(input_file, 'r') as f:
        return json.load(f)


def get_customized_stocks(input_file):
    with open(input_file, 'r') as f:
        return json.load(f)
