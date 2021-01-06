#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2021
import pandas as pd

import logger
from strategies.Strategies import Strategies

pd.options.mode.chained_assignment = None  # default='warn'


class KDJCross(Strategies):
    def __init__(self, input_data: dict, fast_k=9, slow_k=3, slow_d=3, over_buy=80, over_sell=20, observation=100):
        """
        Initialize KDJ-Cross Strategy Instance
        :param input_data:
        :param fast_k: Fast K-Period (Default = 9)
        :param slow_k: Slow K-Period (Default = 3)
        :param slow_d: Slow D-Period (Default = 3)
        :param over_buy: Over-buy Threshold (Default = 80)
        :param over_sell: Over-sell Threshold (Default = 20)
        :param observation: Observation Period in Dataframe (Default = 100)
        """
        self.FAST_K = fast_k
        self.SLOW_K = slow_k
        self.SLOW_D = slow_d
        self.OVER_BUY = over_buy
        self.OVER_SELL = over_sell
        self.OBSERVATION = observation
        self.default_logger = logger.get_logger("kdj_cross")

        super().__init__(input_data)
        self.parse_data()

    def parse_data(self, latest_data: pd.DataFrame = None):
        # Received New Data => Parse it Now to input_data
        if latest_data is not None:
            # Only need to update MACD for the stock_code with new data
            stock_list = [latest_data['code'][0]]

            # Remove records with duplicate time_key. Always use the latest data to override
            time_key = latest_data['time_key'][0]
            self.input_data[stock_list[0]].drop(
                self.input_data[stock_list[0]][self.input_data[stock_list[0]].time_key == time_key].index,
                inplace=True)
            # Append empty columns and concat at the bottom
            latest_data = pd.concat([latest_data, pd.DataFrame(columns=['%k', '%d', '%j'])])
            self.input_data[stock_list[0]] = self.input_data[stock_list[0]].append(latest_data)
        else:
            stock_list = self.input_data.keys()

        # Calculate EMA for the stock_list
        for stock_code in stock_list:
            # Need to truncate to a maximum length for low-latency
            self.input_data[stock_code] = self.input_data[stock_code].iloc[-self.OBSERVATION:]
            self.input_data[stock_code][['open', 'close', 'high', 'low']] = self.input_data[stock_code][
                ['open', 'close', 'high', 'low']].apply(pd.to_numeric)

            low = self.input_data[stock_code]['low'].rolling(9, min_periods=9).min()
            low.fillna(value=self.input_data[stock_code]['low'].expanding().min(), inplace=True)
            high = self.input_data[stock_code]['high'].rolling(9, min_periods=9).max()
            high.fillna(value=self.input_data[stock_code]['high'].expanding().max(), inplace=True)
            rsv = (self.input_data[stock_code]['close'] - low) / (high - low) * 100

            self.input_data[stock_code]['%k'] = pd.DataFrame(rsv).ewm(com=2).mean()
            self.input_data[stock_code]['%d'] = self.input_data[stock_code]['%k'].ewm(com=2).mean()
            self.input_data[stock_code]['%j'] = 3 * self.input_data[stock_code]['%k'] - \
                                                2 * self.input_data[stock_code]['%d']

            self.input_data[stock_code].reset_index(drop=True, inplace=True)

    def buy(self, stock_code) -> bool:

        current_record = self.input_data[stock_code].iloc[-1]
        last_record = self.input_data[stock_code].iloc[-2]
        # Buy Decision based on 当D < 超卖线, K线和D线同时上升，且K线从下向上穿过D线时，买入
        buy_decision = self.OVER_SELL > current_record['%d'] > last_record['%d'] > last_record['%k'] and \
                       current_record['%k'] > last_record['%k'] and \
                       current_record['%k'] > current_record['%d']

        if buy_decision:
            self.default_logger.info(
                f"Buy Decision: {current_record['time_key']} based on \n {pd.concat([last_record.to_frame().transpose(), current_record.to_frame().transpose()], axis=0)}")

        return buy_decision

    def sell(self, stock_code) -> bool:

        current_record = self.input_data[stock_code].iloc[-1]
        last_record = self.input_data[stock_code].iloc[-2]
        # Sell Decision based on 当D > 超买线, K线和D线同时下降，且K线从上向下穿过D线时，卖出
        sell_decision = self.OVER_BUY < current_record['%d'] < last_record['%d'] < last_record['%k'] and \
                        current_record['%k'] < last_record['%k'] and \
                        current_record['%k'] < current_record['%d']

        if sell_decision:
            self.default_logger.info(
                f"Sell Decision: {current_record['time_key']} based on \n {pd.concat([last_record.to_frame().transpose(), current_record.to_frame().transpose()], axis=0)}")
        return sell_decision
