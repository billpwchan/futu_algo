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


import csv
import json
import os
import re
import sqlite3
from datetime import datetime
from multiprocessing import Pool, cpu_count

import humanize
import openpyxl
import pandas as pd
import requests
import yfinance as yf
from deprecated import deprecated

from util import logger
from util.global_vars import *


@deprecated(version='1.0', reason="Database dependency is removed.")
class DatabaseInterface:
    def __init__(self, database_path):
        Path(PATH_DATABASE).mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(database_path)
        self.cur = self.conn.cursor()

    def execute(self, query, data):
        self.cur.execute(query, data)
        return self.cur

    def commit(self):
        self.conn.commit()

    def get_stock_list(self) -> list:
        self.cur.execute('SELECT DISTINCT code FROM stock_data')
        return [item[0] for item in self.cur.fetchall()]

    def add_stock_data(self, code, time_key, open, close, high, low, pe_ratio, turnover_rate, volume, turnover,
                       change_rate, last_close, k_type):
        # if self.check_stock_data_exist(code, time_key, k_type):
        return self.execute(
            "INSERT OR IGNORE INTO stock_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (None, code, time_key, open, close, high, low, pe_ratio, turnover_rate, volume, turnover, change_rate,
             last_close,
             k_type)
        )

    def add_stock_pool(self, date, filter, code):
        return self.execute("INSERT OR IGNORE INTO stock_pool VALUES(?, ?, ?, ?)", (None, date, filter, code))

    def get_stock_pool(self, date, filter):
        # NOT FINISHED YET.
        self.cur.execute("SELECT date, filter, code FROM stock_pool WHERE date=? and filter=?", (date, filter))

    def add_stock_info(self, code, name):
        return self.execute("INSERT OR IGNORE INTO stock_info VALUES(?, ?, ?)", (None, code, name))

    def delete_stock_pool_from_date(self, date):
        return self.execute("DELETE FROM stock_pool WHERE date=?", (date,))

    def __del__(self):
        """ Destroys instance and connection on completion of called method """
        self.conn.close()


class DataProcessingInterface:
    default_logger = logger.get_logger("data_processing")

    @staticmethod
    def validate_dir(dir_path: Path):
        dir_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_1M_data_range(date_range: list, stock_list: list) -> dict:
        """
            Get 1M Data from CSV based on Stock List. Returned in Dict format
        :param date_range: A list of Date in DateTime Format (YYYY-MM-DD)
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :return: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        """
        output_dict = {}
        for stock_code in stock_list:
            # input_df refers to the all the 1M data from start_date to end_date in pd.Dataframe format
            input_df = pd.concat(
                [DataProcessingInterface.get_stock_df_from_file(
                    PATH_DATA / stock_code / f'{stock_code}_{input_date}_1M.parquet')
                    for input_date in date_range if
                    (PATH_DATA / stock_code / f'{stock_code}_{input_date}_1M.parquet').is_file()],
                ignore_index=True)
            input_df[['open', 'close', 'high', 'low']] = input_df[['open', 'close', 'high', 'low']].apply(pd.to_numeric)
            input_df.sort_values(by='time_key', ascending=True, inplace=True)
            output_dict[stock_code] = output_dict.get(stock_code, input_df)
        return output_dict

    @staticmethod
    def get_custom_interval_data(target_date: datetime, custom_interval: int, stock_list: list) -> dict:
        """
            Get 5M/15M/Other Customized-Interval Data from CSV based on Stock List. Returned in Dict format
            Supported Interval: 3M, 5M, 15M, 30M
            Not-Supported Interval: 60M
        :param target_date: Date in DateTime Format (YYYY-MM-DD)
        :param custom_interval: Customized-Interval in unit of "Minutes"
        :param stock_list: A List of Stock Code with Format (e.g., [HK.00001, HK.00002])
        :return: Dictionary in Format {'HK.00001': pd.Dataframe, 'HK.00002': pd.Dataframe}
        """

        input_data = {}
        target_date = target_date.strftime('%Y-%m-%d')
        for stock_code in stock_list:
            input_path = PATH_DATA / stock_code / f'{stock_code}_{target_date}_1M.parquet'

            if not Path(input_path).is_file():
                continue

            input_df = DataProcessingInterface.get_stock_df_from_file(input_path)
            # Non-Trading Day -> Skip
            if input_df.empty:
                continue
            # Set Time-key as Index & Convert to Datetime
            input_df = input_df.set_index('time_key')
            input_df.index = pd.to_datetime(input_df.index, infer_datetime_format=True)
            # Define Function List
            agg_list = {
                "code":          "first",
                "open":          "first",
                "close":         "last",
                "high":          "max",
                "low":           "min",
                "pe_ratio":      "last",
                "turnover_rate": "sum",
                "volume":        "sum",
                "turnover":      "sum",
            }
            # Group from 09:31:00 with Freq = 5 Min
            minute_df = input_df.groupby(
                pd.Grouper(freq=f'{custom_interval}min', closed='left', offset='1min', origin='start')
            ).agg(agg_list)[1:]
            # For 1min -> 5min, need to add Timedelta of 4min
            minute_df.index = minute_df.index + pd.Timedelta(minutes=int(custom_interval - 1))
            # Drop Lunch Time
            minute_df.dropna(inplace=True)

            # Update First Row (Special Cases) e.g. For 1min -> 5min, need to use the first 6min Rows of data
            minute_df.iloc[0] = \
                input_df.iloc[:(custom_interval + 1)].groupby('code').agg(agg_list).iloc[0]

            # Update Last Close Price
            last_index = minute_df.index[0]
            minute_df['change_rate'] = 0
            minute_df['last_close'] = input_df['last_close'][0]
            minute_df.loc[last_index, 'change_rate'] = 100 * (float(minute_df.loc[last_index, 'close']) - float(
                minute_df.loc[last_index, 'last_close'])) / float(minute_df.loc[last_index, 'last_close'])

            # Change Rate = (Close Price - Last Close Price) / Last Close Price * 100
            # Last Close = Previous Close Price
            for index, row in minute_df[1:].iterrows():
                minute_df.loc[index, 'last_close'] = minute_df.loc[last_index, 'close']
                minute_df.loc[index, 'change_rate'] = 100 * (
                        float(row['close']) - float(minute_df.loc[last_index, 'close'])) / float(
                    minute_df.loc[last_index, 'close'])
                last_index = index

            minute_df.reset_index(inplace=True)
            column_names = json.loads(config.get('FutuOpenD.DataFormat', 'HistoryDataFormat'))
            minute_df = minute_df.reindex(columns=column_names)

            # Convert Timestamp type column to standard String format
            minute_df['time_key'] = minute_df['time_key'].dt.strftime('%Y-%m-%d %H:%M:%S')
            input_data[stock_code] = input_data.get(stock_code, minute_df)
        return input_data

    @staticmethod
    def validate_1M_data(date_range: list, stock_list: list, trading_days: dict):
        raise NotImplementedError
        # TODO: Validate data against futu records

    @staticmethod
    def save_stock_df_to_file(data: pd.DataFrame, output_path: str, file_type='parquet') -> bool:
        """
        Save Data to File (CSV / Feather)
        :param data: Data to Save
        :param output_path: File Name to Save
        :param file_type: File Type to Save (CSV / Feather / Parquet)
        :return: None
        """
        if not data.empty:
            if file_type == 'csv':
                data.to_csv(output_path, index=False, encoding='utf-8-sig')
            elif file_type == 'parquet':
                data.to_parquet(output_path, index=False)
            return True
        return False

    @staticmethod
    def get_stock_df_from_file(input_path: Path) -> pd.DataFrame:
        """
        Load Data from File (CSV / Feather / Parquet)
        :param input_path: File Name to Load
        :return: DataFrame
        """
        data = pd.DataFrame(columns=json.loads(config.get('FutuOpenD.DataFormat', 'HistoryDataFormat')))
        if input_path.suffix == '.csv':
            data = pd.read_csv(input_path, index_col=None, encoding='utf-8-sig')
        elif input_path.suffix == '.parquet':
            data = pd.read_parquet(input_path)
        return data

    @staticmethod
    def check_empty_data(input_path: Path) -> bool:
        """
        Check if the input file is empty
        :param input_path:
        :return:
        """
        input_df = DataProcessingInterface.get_stock_df_from_file(input_path)
        if input_df.empty:
            input_path.unlink()
            DataProcessingInterface.default_logger.info(f'{input_path} removed.')
            return True
        return False

    @staticmethod
    def clear_empty_data():
        pool = Pool(cpu_count())
        pool.map(DataProcessingInterface.check_empty_data, PATH_DATA.rglob("*/*_1[DWM].parquet"))
        pool.close()
        pool.join()

    @staticmethod
    def convert_csv_to_parquet(input_file: Path) -> bool:
        """
        Convert CSV file to Parquet file
        :param input_file: File to Convert
        :return: bool
        """
        if input_file.suffix == '.csv':
            output_file = input_file.as_posix().replace('.csv', '.parquet')
            output_file = Path(output_file)
            # Temporary
            output_file.parent.mkdir(parents=True, exist_ok=True)
            DataProcessingInterface.default_logger.info(f'Converting {input_file} to {output_file}')
            df = pd.read_csv(input_file, index_col=None)
            df.to_parquet(output_file, index=False)
            return True
        return False

    @staticmethod
    def convert_parquet_to_csv(input_file: Path) -> bool:
        """
        Convert Parquet file to CSV file
        :param input_file: File to Convert
        :return: bool
        """
        if input_file.suffix == '.parquet':
            output_file = input_file.as_posix().replace('.parquet', '.csv')
            DataProcessingInterface.default_logger.info(f'Converting {input_file} to {output_file}')
            df = pd.read_parquet(input_file)
            df.to_csv(output_file, index=False)
            return True
        return False

    @staticmethod
    def convert_all_csv_to_parquet():
        pool = Pool(cpu_count())
        pool.map(DataProcessingInterface.convert_csv_to_parquet, PATH_DATA.rglob("*/*_1[DWM].csv"))
        pool.close()
        pool.join()

    @staticmethod
    def get_num_days_to_update(stock_code) -> int:
        return (datetime.now() - datetime.fromtimestamp(
            Path(max((PATH_DATA / stock_code).glob('*.parquet'), key=os.path.getctime)).stat().st_mtime)).days


class YahooFinanceInterface:
    @staticmethod
    def __validate_stock_code(stock_list: list) -> list:
        """
            Check stock code format, and always return Yahoo Finance Stock Code format
            Use Internally
        :param stock_list: Either in Futu Format (Starts with HK/US) / Yahoo Finance Format (Starts with Number)
        :return: Stock code list in Yahoo Finance format
        """
        return [YahooFinanceInterface.futu_code_to_yfinance_code(stock_code) if stock_code[:1].isalpha() else stock_code
                for stock_code in stock_list]

    @staticmethod
    def get_top_30_hsi_constituents() -> list:
        r = requests.get('https://finance.yahoo.com/quote/%5EHSI/components/', headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})
        payload = pd.read_html(r.text)[0]
        return [YahooFinanceInterface.yfinance_code_to_futu_code(stock_code) for stock_code in
                payload['Symbol'].tolist()]

    @staticmethod
    def futu_code_to_yfinance_code(futu_code: str) -> str:
        """
            Convert Futu Stock Code to Yahoo Finance Stock Code format
            E.g., HK.09988 -> 9988.HK
        :param futu_code: Stock code used in Futu (e.g., HK.09988)
        """
        assert re.match(r'^[A-Z]{2}.\d{5}$', futu_code)
        return '.'.join(reversed(futu_code.split('.')))[1:]

    @staticmethod
    def yfinance_code_to_futu_code(yfinance_code: str) -> str:
        """
            Convert Yahoo Finance Stock Code to Futu Stock Code format
            E.g., 9988.HK -> HK.09988
        :param yfinance_code: Stock code used in Yahoo Finance (e.g., 9988.HK)
        """
        assert re.match(r'^\d{4}.[A-Z]{2}$', yfinance_code)
        return '.'.join(reversed(('0' + yfinance_code).split('.')))

    @staticmethod
    def get_stocks_info(stock_list: list) -> dict:
        stock_list = YahooFinanceInterface.__validate_stock_code(stock_list)
        return {stock_code: yf.Ticker(stock_code).info for stock_code in stock_list}

    @staticmethod
    def get_stock_info(stock_code: str) -> dict:
        try:
            stock_code = YahooFinanceInterface.__validate_stock_code([stock_code])[0]
            return yf.Ticker(stock_code).info
        except:
            return {}

    @staticmethod
    def get_stocks_name(stock_list: list) -> dict:
        stock_list = YahooFinanceInterface.__validate_stock_code(stock_list)
        return {stock_code: yf.Ticker(stock_code).info['longName'] for stock_code in stock_list}

    @staticmethod
    def get_stocks_email(stock_list: list) -> dict:
        stock_list = YahooFinanceInterface.__validate_stock_code(stock_list)
        output_dict = {}
        for stock_code in stock_list:
            stock_info = yf.Ticker(stock_code).info
            output_dict[stock_code] = {'longName':              stock_info.get('longName', 'N/A'),
                                       'previousClose':         f"{stock_info.get('currency', 'N/A')} {stock_info.get('previousClose', 'N/A')}",
                                       'open':                  f"{stock_info.get('currency', 'N/A')} {stock_info.get('open', 'N/A')}",
                                       'dayRange':              f"{stock_info.get('currency', 'N/A')} {stock_info.get('dayLow', 'N/A')}-{stock_info.get('dayHigh', 'N/A')}",
                                       'marketCap':             f"{stock_info.get('currency', 'N/A')} {humanize.intword(stock_info.get('marketCap', 'N/A'))}",
                                       'beta':                  f"{stock_info.get('beta', 'N/A')}",
                                       'PE(Trailing/Forward)':  f"{stock_info.get('trailingPE', 'N/A')} / {stock_info.get('forwardPE', 'N/A')}",
                                       'EPS(Trailing/Forward)': f"{stock_info.get('trailingEps', 'N/A')} / {stock_info.get('forwardEps', 'N/A')}",
                                       'volume':                humanize.intword(stock_info.get('volume', 'N/A'))}
        return output_dict

    @staticmethod
    def get_stocks_history(stock_list: list) -> pd.DataFrame:
        stock_list = YahooFinanceInterface.__validate_stock_code(stock_list)
        return yf.download(stock_list, group_by="ticker", auto_adjust=True, actions=True, progress=False)

    @staticmethod
    def get_stock_history(stock_code: str) -> pd.DataFrame:
        stock_code = YahooFinanceInterface.__validate_stock_code([stock_code])[0]
        return yf.download(stock_code, auto_adjust=True, actions=True, progress=False)

    @staticmethod
    def parse_stock_info(stock_code: str):
        return stock_code, YahooFinanceInterface.get_stock_info(stock_code)


class HKEXInterface:

    @staticmethod
    def update_security_list_full() -> None:
        """
            Get Full Security List from HKEX. Can Daily Update (Override)
            URL: https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx
        """
        full_stock_list = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
        resp = requests.get(full_stock_list)
        with open(PATH_DATA / 'Stock_Pool' / 'ListOfSecurities.xlsx', 'wb') as fp:
            fp.write(resp.content)

        wb = openpyxl.load_workbook(PATH_DATA / 'Stock_Pool' / 'ListOfSecurities.xlsx')
        sh = wb.active
        with open(PATH_DATA / 'Stock_Pool' / 'ListOfSecurities.csv', 'w', newline="") as f:
            c = csv.writer(f)
            for r in sh.rows:
                c.writerow([cell.value for cell in r])

    @staticmethod
    def get_security_df_full() -> pd.DataFrame:
        input_csv = pd.read_csv(PATH_DATA / 'Stock_Pool' / 'ListOfSecurities.csv', index_col=None, skiprows=2,
                                dtype={'Stock Code': str})
        input_csv.dropna(subset=['Stock Code'], inplace=True)
        input_csv.drop(input_csv.columns[-1], axis=1, inplace=True)
        input_csv.set_index('Stock Code')
        return input_csv

    @staticmethod
    def get_equity_list_full() -> list:
        """
            Return Full List of Equity in FuTu Stock Code Format E.g. HK.00001
        :return:
        """
        input_csv = HKEXInterface.get_security_df_full()
        return [('HK.' + item) for item in input_csv[input_csv['Category'] == 'Equity']['Stock Code'].tolist()]

    @staticmethod
    def get_equity_info_full() -> list:
        """
            Return Full List of Equity dict in Futu Stock Code Format including Basic Info
            E.g., {"Stock Code": HK.00001, "Name of Securities": "CKH HOLDINGS", "Board Lot": 500}
        """
        input_csv = HKEXInterface.get_security_df_full()
        return [{"Stock Code": f'HK.{row["Stock Code"]}', "Name of Securities": row["Name of Securities"],
                 "Board Lot":  row["Board Lot"]} for index, row in
                input_csv[input_csv['Category'] == 'Equity'].iterrows()]

    @staticmethod
    def get_board_lot_full() -> dict:
        """
            Return Full Dict of the Board Lot Size (Minimum Trading Unit) for each stock E.g. {'HK.00001': 500}
        """
        input_csv = HKEXInterface.get_security_df_full()
        return {('HK.' + row['Stock Code']): int(row['Board Lot'].replace(',', '')) for index, row in
                input_csv[input_csv['Category'] == 'Equity'].iterrows()}
