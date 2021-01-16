#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import sqlite3


class DatabaseInterface:
    def __init__(self, database_path):
        self.conn = sqlite3.connect(database_path)
        self.cur = self.conn.cursor()

    def execute(self, query, data):
        self.cur.execute(query, data)
        # self.conn.commit()
        return self.cur

    def commit(self):
        self.conn.commit()

    def check_stock_data_exist(self, code, time_key, k_type):
        self.cur.execute('SELECT * FROM stock_data WHERE (code=? AND time_key=? AND k_type=?)',
                         (code, time_key, k_type))
        entry = self.cur.fetchone()
        return entry is None

    def add_stock_data(self, code, time_key, open, close, high, low, pe_ratio, turnover_rate, volume, turnover,
                       change_rate, last_close, k_type):
        # if self.check_stock_data_exist(code, time_key, k_type):
        return self.execute(
            "INSERT OR IGNORE INTO stock_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (None, code, time_key, open, close, high, low, pe_ratio, turnover_rate, volume, turnover, change_rate,
             last_close,
             k_type)
        )

    def add_stock_data_bulk(self, to_db):
        self.cur.executemany("INSERT OR IGNORE INTO stock_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             to_db)
        self.conn.commit()

    def __del__(self):
        """ Destroys instance and connection on completion of called method """
        self.conn.close()


class YahooFinanceInterface:
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
    def __validate_stock_code(stock_code: str) -> str:
        """
            Check stock code format, and always return Yahoo Finance Stock Code format
            Use Internally
        :param stock_code: Either in Futu Format (Starts with HK/US) / Yahoo Finance Format (Starts with Number)
        :return: Stock code in Yahoo Finance format
        """
        return YahooFinanceInterface.futu_code_to_yfinance_code(stock_code) if stock_code[:1].isalpha() else stock_code

    @staticmethod
    def update_stock_info(stock_code: str):
        stock_code = YahooFinanceInterface.__validate_stock_code(stock_code)
