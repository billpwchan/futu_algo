#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import sqlite3


class DatabaseInterface:
    def __init__(self, database_path):
        self.conn = sqlite3.connect(database_path)
        self.cur = self.conn.cursor()

    def execute(self, query, data):
        self.cur.execute(query, data)
        self.conn.commit()
        return self.cur

    def check_stock_data_exist(self, code, time_key, kl_type):
        self.cur.execute('SELECT * FROM stock_data WHERE (code=? AND time_key=? AND kl_type=?)',
                         (code, time_key, kl_type))
        entry = self.cur.fetchone()
        return entry is None

    def add_stock_data(self, code, time_key, open, close, high, low, pe_ratio, turnover_rate, volume, turnover,
                       change_rate, last_close, kl_type):
        if self.check_stock_data_exist(code, time_key, kl_type):
            return self.execute(
                "INSERT INTO stock_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (None, code, time_key, open, close, high, low, pe_ratio, turnover_rate, volume, turnover, change_rate,
                 last_close,
                 kl_type)
            )

    def __del__(self):
        """ Destroys instance and connection on completion of called method """
        self.conn.close()
