#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

# ///////////////////////////////////////////////////////////////
#

# PROJECT MADE WITH: Qt Designer and PySide6
# V: 1.0.0
#
# This project can be used freely for all uses, as long as they maintain the
# respective credits only in the Python scripts, any information in the visual
# interface (GUI) can be modified without any implication.
#
# There are limitations on Qt licenses if you want to use your products
# commercially, I recommend reading them on the official website:
# https://doc.qt.io/qtforpython/licenses.html
#
# ///////////////////////////////////////////////////////////////
import configparser
import glob
import json
import os
import sys
import platform

# IMPORT / GUI AND MODULES AND WIDGETS
# ///////////////////////////////////////////////////////////////
from pathlib import Path

from engines.data_engine import HKEXInterface
from modules import *
from widgets import *

# SET AS GLOBAL WIDGETS
# ///////////////////////////////////////////////////////////////
widgets = None


class MainWindow(QMainWindow):
    def __init__(self):
        QMainWindow.__init__(self)

        # SET AS GLOBAL WIDGETS
        # ///////////////////////////////////////////////////////////////
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        global widgets
        widgets = self.ui

        # USE CUSTOM TITLE BAR | USE AS "False" FOR MAC OR LINUX
        # ///////////////////////////////////////////////////////////////
        Settings.ENABLE_CUSTOM_TITLE_BAR = True

        # APP NAME
        # ///////////////////////////////////////////////////////////////
        title = "FUTU ALGO - Trading Solution"
        description = "FUTU ALGO - Your First Step to Algorithmic Trading"
        # APPLY TEXTS
        self.setWindowTitle(title)
        widgets.titleRightInfo.setText(description)

        # Initialize COMBOBOX SET VALUES
        self.__initialize_values()

        # TOGGLE MENU
        # ///////////////////////////////////////////////////////////////
        widgets.toggleButton.clicked.connect(lambda: UIFunctions.toggleMenu(self, True))

        # SET UI DEFINITIONS
        # ///////////////////////////////////////////////////////////////
        UIFunctions.uiDefinitions(self)

        # QTableWidget PARAMETERS
        # ///////////////////////////////////////////////////////////////
        widgets.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # BUTTONS CLICK
        # ///////////////////////////////////////////////////////////////

        # LEFT MENUS
        widgets.btn_home.clicked.connect(self.buttonClick)
        widgets.btn_widgets.clicked.connect(self.buttonClick)
        widgets.btn_stock_trading.clicked.connect(self.buttonClick)
        widgets.btn_save.clicked.connect(self.buttonClick)

        # EXTRA LEFT BOX
        def openCloseLeftBox():
            UIFunctions.toggleLeftBox(self, True)

        widgets.toggleLeftBox.clicked.connect(openCloseLeftBox)
        widgets.extraCloseColumnBtn.clicked.connect(openCloseLeftBox)

        # EXTRA RIGHT BOX
        def openCloseRightBox():
            UIFunctions.toggleRightBox(self, True)

        widgets.settingsTopBtn.clicked.connect(openCloseRightBox)

        # SHOW APP
        # ///////////////////////////////////////////////////////////////
        self.show()

        # SET CUSTOM THEME
        # ///////////////////////////////////////////////////////////////
        useCustomTheme = False
        themeFile = "themes\py_dracula_light.qss"

        # SET THEME AND HACKS
        if useCustomTheme:
            # LOAD AND APPLY STYLE
            UIFunctions.theme(self, themeFile, True)

            # SET HACKS
            AppFunctions.setThemeHack(self)

        # SET HOME PAGE AND SELECT MENU
        # ///////////////////////////////////////////////////////////////
        widgets.stackedWidget.setCurrentWidget(widgets.home)
        widgets.btn_home.setStyleSheet(UIFunctions.selectMenu(widgets.btn_home.styleSheet()))

    def __initialize_values(self):
        # Initialize Config Parser
        config = configparser.ConfigParser()
        config.read("config.ini")

        # Stock Trading ComboBox
        strategy_list = [Path(file_name).name[:-3] for file_name in glob.glob("./strategies/*.py") if
                         "__init__" not in file_name and "Strategies" not in file_name]
        self.ui.stockTradingStrategyList.clear()
        self.ui.stockTradingStrategyList.addItems(strategy_list)

        # Stock Trading ComboBox
        time_interval_list = ["1M", "3M", "5M", "15M", "30M", "60M", "DAY", "WEEK", "MON", "QUARTER", "YEAR"]
        self.ui.stockTradingInterval.clear()
        self.ui.stockTradingInterval.addItems(time_interval_list)

        # Stock Trading Table - Stock List
        stock_list = json.loads(config.get('TradePreference', 'StockList'))
        if not stock_list:
            # Directly get list of stock codes from the data folder. Easier.
            stock_list = [str(f.path).replace('./data/', '') for f in os.scandir("./data/") if f.is_dir()]
            stock_list = stock_list[:-1]

        # Stock Trading Clear Table
        self.ui.stockTradingTable.clearContents()
        self.ui.stockTradingTable.setRowCount(0)

        equity_info_full = HKEXInterface.get_equity_info_full()
        assert equity_info_full
        headers = equity_info_full[0].keys()
        self.ui.stockTradingTable.setColumnCount(len(headers))
        self.ui.stockTradingTable.setHorizontalHeaderLabels(headers)

        for stock in equity_info_full:
            if stock["Stock Code"] in stock_list:
                row_number = self.ui.stockTradingTable.rowCount()
                self.ui.stockTradingTable.insertRow(row_number)
                for column_number, column_name in enumerate(headers):
                    self.ui.stockTradingTable.setItem(row_number, column_number, QTableWidgetItem(stock[column_name]))

        self.ui.stockTradingTable.resizeColumnsToContents()

        self.ui.stockTradingConfigButton.clicked.connect(lambda: self.__openFile(filters='Config files (*.ini)'))

    def __openFile(self, filters: str):
        path = QFileDialog.getOpenFileName(self, 'Open file', '', filters)
        if path != ('', ''):
            print("File path : " + path[0])

    def buttonClick(self):
        # GET BUTTON CLICKED
        btn = self.sender()
        btnName = btn.objectName()

        # SHOW HOME PAGE
        if btnName == "btn_home":
            widgets.stackedWidget.setCurrentWidget(widgets.home)
            UIFunctions.resetStyle(self, btnName)
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))

        # SHOW WIDGETS PAGE
        if btnName == "btn_widgets":
            widgets.stackedWidget.setCurrentWidget(widgets.widgets)
            UIFunctions.resetStyle(self, btnName)
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))

        # SHOW NEW PAGE
        if btnName == "btn_stock_trading":
            widgets.stackedWidget.setCurrentWidget(widgets.stock_trading)  # SET PAGE
            UIFunctions.resetStyle(self, btnName)  # RESET ANOTHERS BUTTONS SELECTED
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))  # SELECT MENU

        if btnName == "btn_save":
            print("Save BTN clicked!")

        # PRINT BTN NAME
        print(f'Button "{btnName}" pressed!')

    def resizeEvent(self, event):
        # Update Size Grips
        UIFunctions.resize_grips(self)

    def mousePressEvent(self, event):
        # SET DRAG POS WINDOW
        self.dragPos = event.globalPos()

        # PRINT MOUSE EVENTS
        if event.buttons() == Qt.LeftButton:
            print('Mouse click: LEFT CLICK')
        if event.buttons() == Qt.RightButton:
            print('Mouse click: RIGHT CLICK')


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("icon.ico"))
    window = MainWindow()
    sys.exit(app.exec_())
