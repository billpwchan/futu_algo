#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#   Proprietary and confidential
#   Written by Bill Chan <billpwchan@hotmail.com>, 2020

import trading_utils


def main():
    # Initialization Connection
    futu_trade = trading_utils.FutuTrade()
    try:
        # Daily Update HSI Constituents & Customized Stocks
        hsi_constituents = trading_utils.get_hsi_constituents(
            './data/HSI.Constituents/HSI_constituents_2020-12-22.json')
        customized_stocks = trading_utils.get_customized_stocks('./data/Customized/Customized_Stocks_2020-12-23.json')
        for stock_code in hsi_constituents:
            futu_trade.update_1M_data(stock_code)
        for stock_code in customized_stocks:
            futu_trade.update_1M_data(stock_code)

        # handler = trading_utils.StockQuoteHandler()
        # futu_trade.quote_ctx.set_handler(handler)  # 设置实时报价回调
        # futu_trade.quote_ctx.subscribe(['HK.00700'], [SubType.QUOTE])  # 订阅实时报价类型，FutuOpenD开始持续收到服务器的推送
        # time.sleep(60)  # 设置脚本接收FutuOpenD的推送持续时间为15秒

    finally:
        ret, data = futu_trade.quote_ctx.query_subscription()
        trading_utils.display_result(ret, data)
        ret, data = futu_trade.quote_ctx.get_history_kl_quota(get_detail=True)  # 设置True代表需要返回详细的拉取历史K 线的记录
        trading_utils.display_result(ret, data)
        futu_trade.quote_ctx.close()


if __name__ == '__main__':
    main()
