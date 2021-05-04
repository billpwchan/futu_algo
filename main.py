#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

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
from modules.ui_splash_screen import Ui_SplashScreen
import webbrowser as webbrowser

# SET AS GLOBAL WIDGETS
# ///////////////////////////////////////////////////////////////
widgets = None

# GLOBALS
counter = 0
GITHUB_LINK = "https://github.com/billpwchan/futu_algo"
LINKEDIN_LINK = "https://www.linkedin.com/in/billpwchan1998/"


class SplashScreen(QMainWindow):
    def __init__(self):
        QMainWindow.__init__(self)
        self.ui = Ui_SplashScreen()
        self.ui.setupUi(self)

        # REMOVE TITLE BAR
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # IMPORT CIRCULAR PROGRESS
        self.progress = CircularProgress()
        self.progress.width = 270
        self.progress.height = 270
        self.progress.value = 0
        self.progress.setFixedSize(self.progress.width, self.progress.height)
        self.progress.move(15, 15)
        self.progress.font_size = 40
        self.progress.add_shadow(True)
        self.progress.progress_width = 5
        self.progress.bg_color = QColor(68, 71, 90, 140)
        self.progress.setParent(self.ui.centralwidget)
        self.progress.show()

        # ADD DROP SHADOW
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(15)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(0)
        self.shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(self.shadow)

        # QTIMER
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(10)

        self.show()

    # UPDATE PROGRESS BAR
    def update(self):
        global counter

        # SET VALUE TO PROGRESS BAR
        self.progress.set_value(counter)

        # CLOSE SPLASH SCREEN AND OPEN MAIN APP
        if counter >= 100:
            # STOP TIMER
            self.timer.stop()

            # SHOW MAIN WINDOW
            self.main = MainWindow()
            self.main.show()

            # CLOSE SPLASH SCREEN
            self.close()

        # INCREASE COUNTER
        counter += 1


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
        self.__initialize_global_values()
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
        widgets.btn_settings.clicked.connect(self.buttonClick)

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
        themeFile = "themes\py_dracula_dark.qss"

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

    def __open_url(self, url):
        webbrowser.open(url)

    def __initialize_global_values(self):
        self.ui.bottomBarGithubButton.clicked.connect(lambda: self.__open_url(GITHUB_LINK))
        self.ui.bottomBarLinkedInButton.clicked.connect(lambda: self.__open_url(LINKEDIN_LINK))

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

        self.ui.settingsConfigButton.clicked.connect(lambda: self.__openFile(filters='Config files (*.ini)'))
        self.ui.settingsMapButton.clicked.connect(lambda: self.__openFile(filters='YAML files (*.yml)'))

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

        # SHOW STOCK TRADING PAGE
        if btnName == "btn_stock_trading":
            widgets.stackedWidget.setCurrentWidget(widgets.stock_trading)  # SET PAGE
            UIFunctions.resetStyle(self, btnName)  # RESET ANOTHERS BUTTONS SELECTED
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))  # SELECT MENU

        # SHOW SETTINGS PAGE
        if btnName == "btn_settings":
            widgets.stackedWidget.setCurrentWidget(widgets.settings)  # SET PAGE
            UIFunctions.resetStyle(self, btnName)  # RESET ANOTHERS BUTTONS SELECTED
            btn.setStyleSheet(UIFunctions.selectMenu(btn.styleSheet()))  # SELECT MENU

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
    window = SplashScreen()
    sys.exit(app.exec_())
