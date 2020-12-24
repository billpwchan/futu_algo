#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import configparser
import datetime
import glob
from pathlib import Path

from futu import *

import logger


class StockQuoteHandler(StockQuoteHandlerBase):
    def __init__(self):
        self.default_logger = logger.get_logger('stock_quote')
        super().__init__()

    def on_recv_rsp(self, rsp_str):
        ret_code, data = super(StockQuoteHandler, self).on_recv_rsp(rsp_str)
        if ret_code != RET_OK:
            self.default_logger.error("StockQuoteTest: error, msg: %s" % data)
            return RET_ERROR, data
        # MACD Crossover Logic PoC
        # macd_cross = MACDCross(input_data)
        # macd_cross.parse_data(latest_data)
        return RET_OK, data


class FutuTrade():
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read("config.ini")
        self.quote_ctx = OpenQuoteContext(host=self.config['FutuOpenD.Config'].get('Host'),
                                          port=self.config['FutuOpenD.Config'].getint('Port'))
        # Initialize Subscription Logic
        self.handler = StockQuoteHandler()
        self.quote_ctx.set_handler(handler=self.handler)
        self.default_logger = logger.get_logger("futu_trade")

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.quote_ctx.close()  # 关闭当条连接，FutuOpenD会在1分钟后自动取消相应股票相应类型的订阅

    def __del__(self):
        self.quote_ctx.close()  # 关闭当条连接，FutuOpenD会在1分钟后自动取消相应股票相应类型的订阅

    def get_market_state(self):
        return self.quote_ctx.get_global_state()

    def save_historical_data(self, stock_code, start_date, end_date, k_type):
        out_dir = f'./data/{stock_code}'
        if not os.path.exists(out_dir):
            os.mkdir(out_dir)
        output_path = f'./data/{stock_code}/{stock_code}_{start_date}_1M.csv'
        # Ensure update current day's 1M data
        if os.path.exists(output_path) and start_date != str(datetime.today().date()):
            return False
        # Request Historical K-line Data (Daily)
        ret, data, page_req_key = self.quote_ctx.request_history_kline(stock_code, start=start_date,
                                                                       end=end_date,
                                                                       ktype=k_type, autype=AuType.QFQ,
                                                                       fields=[KL_FIELD.ALL],
                                                                       max_count=1000, page_req_key=None,
                                                                       extended_time=False)
        if ret == RET_OK:
            data.to_csv(output_path, index=False)
            self.default_logger.info(f'Saved: {output_path}')
        else:
            self.default_logger.error(f'Historical Data Store Error: {data}')
        return True

    def update_1M_data(self, stock_code, years=2):
        for i in range(365 * years):
            day = datetime.today() - timedelta(days=i)
            if not self.save_historical_data(stock_code, str(day.date()), str(day.date()),
                                             KLType.K_1M):
                continue
            time.sleep(0.5)

    def stock_price_subscription(self, stock_code) -> bool:
        delta = 0
        while not Path(
                f'./data/{stock_code}/{stock_code}_{str((datetime.today() - timedelta(days=delta)).date())}_1M.csv').exdeltasts():
            delta += 1
        if delta > 1:
            self.default_logger.error(
                "Subscription Failed: Outdated Data. Please use update_{time_period}_data function to update")
            return False
        # handler = StockQuoteHandler()
        # futu_trade.quote_ctx.set_handler(handler)  # 设置实时报价回调
        # futu_trade.quote_ctx.subscribe(['HK.00700'], [SubType.QUOTE])  # 订阅实时报价类型，FutuOpenD开始持续收到服务器的推送
        # time.sleep(60)  # 设置脚本接收FutuOpenD的推送持续时间为15秒


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


def timeit(method):
    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()
        if 'log_time' in kw:
            name = kw.get('log_name', method.__name__.upper())
            kw['log_time'][name] = int((te - ts) * 1000)
        else:
            print('%r  %2.2f ms' % (method.__name__, (te - ts) * 1000))
        return result

    return timed
