#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import csv
import sqlite3

import humanize
import openpyxl
import pandas as pd
import requests
import yfinance as yf


class DatabaseInterface:
    def __init__(self, database_path):
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


class YahooFinanceInterface:
    @staticmethod
    def get_top_30_hsi_constituents() -> list:
        payload = pd.read_html('https://finance.yahoo.com/quote/%5EHSI/components/')[0]
        return [YahooFinanceInterface.yfinance_code_to_futu_code(stock_code) for stock_code in
                payload['Symbol'].tolist()]

    @staticmethod
    def futu_code_to_yfinance_code(futu_code: str) -> str:
        """
            Convert Futu Stock Code to Yahoo Finance Stock Code format
            E.g., HK.09988 -> 9988.HK
        :param futu_code: Stock code used in Futu (e.g., HK.09988)
        """
        return '.'.join(reversed(futu_code.split('.')))[1:]

    @staticmethod
    def yfinance_code_to_futu_code(yfinance_code: str) -> str:
        """
            Convert Yahoo Finance Stock Code to Futu Stock Code format
            E.g., 9988.HK -> HK.09988
        :param yfinance_code: Stock code used in Yahoo Finance (e.g., 9988.HK)
        """
        return '.'.join(reversed(('0' + yfinance_code).split('.')))

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
            output_dict[stock_code] = {'longName': stock_info['longName'],
                                       'previousClose': f"{stock_info['currency']} {stock_info['previousClose']}",
                                       'open': f"{stock_info['currency']} {stock_info['open']}",
                                       'dayRange': f"{stock_info['currency']} {stock_info['dayLow']}-{stock_info['dayHigh']}",
                                       'marketCap': f"{stock_info['currency']} {stock_info['marketCap']}",
                                       'beta': f"{stock_info['beta']}",
                                       'PE(Trailing/Forward)': f"{stock_info['trailingPE']}, {stock_info['forwardPE']}",
                                       'EPS(Trailing/Forward)': f"{stock_info['trailingEps']}, {stock_info['forwardEps']}",
                                       'volume': humanize.intword(stock_info['volume'])}
        return output_dict

    @staticmethod
    def get_stocks_history(stock_list: list) -> pd.DataFrame:
        stock_list = YahooFinanceInterface.__validate_stock_code(stock_list)
        return yf.download(stock_list, period="max", group_by="ticker", auto_adjust=True, actions=True, progress=False)

    @staticmethod
    def get_stock_history(stock_code: str) -> pd.DataFrame:
        stock_code = YahooFinanceInterface.__validate_stock_code([stock_code])[0]
        return yf.download(stock_code, period="max", auto_adjust=True, actions=True, progress=False)


class HKEXInterface:

    @staticmethod
    def update_security_list_full() -> None:
        """
            Get Full Security List from HKEX. Can Daily Update (Override)
            URL: https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx
        """
        full_stock_list = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
        resp = requests.get(full_stock_list)
        with open('./data/Stock_Pool/ListOfSecurities.xlsx', 'wb') as fp:
            fp.write(resp.content)

        wb = openpyxl.load_workbook('./data/Stock_Pool/ListOfSecurities.xlsx')
        sh = wb.active
        with open('./data/Stock_Pool/ListOfSecurities.csv', 'w', newline="") as f:
            c = csv.writer(f)
            for r in sh.rows:
                c.writerow([cell.value for cell in r])

    @staticmethod
    def get_security_df_full() -> pd.DataFrame:
        input_csv = pd.read_csv('./data/Stock_Pool/ListOfSecurities.csv', index_col=None, skiprows=2,
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
    def get_board_lot_full() -> dict:
        """
            Return Full Dict of the Board Lot Size (Minimum Trading Unit) for each stock E.g. {'HK.00001': 500}
        """
        input_csv = HKEXInterface.get_security_df_full()
        return {('HK.' + row['Stock Code']): int(row['Board Lot'].replace(',', '')) for index, row in
                input_csv[input_csv['Category'] == 'Equity'].iterrows()}
