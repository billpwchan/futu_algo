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
#  C PySide6 import QtGui
from PySide6.QtWidgets import QMessageBox
import pyqtgraph as pg

from engines import *
from modules import *
from widgets import *
from util import *
import webbrowser as webbrowser

import configparser
import glob
import json
import os
import sys
import platform
from pathlib import Path

# GLOBALS
counter = 0
GLOBAL_STATE = False
GLOBAL_TITLE_BAR = True

GITHUB_LINK = "https://github.com/billpwchan/futu_algo"
LINKEDIN_LINK = "https://www.linkedin.com/in/billpwchan1998/"
APP_TITLE = "FUTU ALGO - Trading Solution"
APP_DESCRIPTION = "FUTU ALGO - Your First Step to Algorithmic Trading"
APP_LOGO_SMALL = "./images/images/PyDracula.png"

# Initialization Connection

futu_trade = trading_engine.FutuTrade()
email_handler = email_engine.Email()


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
        self.progress.setFixedWidth(self.progress.width)
        self.progress.setFixedHeight(self.progress.height)
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
        self.timer.start()

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
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.ui = self.ui

        # USE CUSTOM TITLE BAR | USE AS "False" FOR MAC OR LINUX
        Settings.ENABLE_CUSTOM_TITLE_BAR = True

        # APPLY TEXTS
        self.setWindowTitle(APP_TITLE)
        self.ui.titleRightInfo.setText(APP_DESCRIPTION)

        # Initialize COMBOBOX SET VALUES
        self.__initialize_global_values()

        # Add Custom Checkbox
        # self.ui.verticalLayout_27.addWidget(PyToggle(), Qt.AlignCenter, Qt.AlignCenter)

        # TOGGLE MENU
        self.ui.toggleButton.clicked.connect(lambda: self.toggleMenu(True))

        # SET UI DEFINITIONS
        self.uiDefinitions()

        # QTableWidget PARAMETERS
        self.ui.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # LEFT MENUS
        self.ui.btn_home.clicked.connect(self.button_click_handler)
        self.ui.btn_widgets.clicked.connect(self.button_click_handler)
        self.ui.btn_stock_trading.clicked.connect(self.button_click_handler)
        self.ui.btn_settings.clicked.connect(self.button_click_handler)

        # EXTRA LEFT BOX
        def openCloseLeftBox():
            self.toggleLeftBox(True)

        self.ui.toggleLeftBox.clicked.connect(openCloseLeftBox)
        self.ui.extraCloseColumnBtn.clicked.connect(openCloseLeftBox)

        # EXTRA RIGHT BOX
        def openCloseRightBox():
            self.toggleRightBox(True)

        self.ui.settingsTopBtn.clicked.connect(openCloseRightBox)

        # SHOW APP
        self.show()

        # SET CUSTOM THEME
        useCustomTheme = False
        themeFile = "themes\py_dracula_dark.qss"

        # SET THEME AND HACKS
        if useCustomTheme:
            # LOAD AND APPLY STYLE
            self.theme(themeFile, True)

            # SET HACKS
            self.__setThemeHack()

        # SET HOME PAGE AND SELECT MENU
        self.ui.stackedWidget.setCurrentWidget(self.ui.home)
        self.ui.btn_home.setStyleSheet(self.selectMenu(self.ui.btn_home.styleSheet()))

    def __initialize_global_values(self):
        self.ui.bottomBarGithubButton.clicked.connect(lambda: self.__open_url(GITHUB_LINK))
        self.ui.bottomBarLinkedInButton.clicked.connect(lambda: self.__open_url(LINKEDIN_LINK))

        def setConfigFile():
            # Initialize Config File
            global config
            config = configparser.ConfigParser()
            file_path = self.__open_file(filters='Config files (*.ini)')
            self.ui.settingsConfigLabel.setText(file_path)
            config.read(file_path)

        def setStrategyMapFile():
            file_path = self.__open_file(filters='YAML files (*.yml)')
            self.ui.settingsMapLabel.setText(file_path)
            global stock_strategy_map
            with open(file_path, 'r') as infile:
                stock_strategy_map = yaml.safe_load(infile)

        self.ui.settingsConfigButton.clicked.connect(setConfigFile)
        self.ui.settingsMapButton.clicked.connect(setStrategyMapFile)

    def __initialize_stock_trading_values(self):
        global config
        global stock_strategy_map

        # Stock Trading Strategy Config
        strategy_list = [Path(file_name).name[:-3] for file_name in glob.glob("./strategies/*.py") if
                         "__init__" not in file_name and "Strategies" not in file_name]
        self.ui.stockTradingStrategyListValue.clear()
        self.ui.stockTradingStrategyListValue.addItems(strategy_list)

        # Stock Trading Mapping Config
        time_interval_list = ["1M", "3M", "5M", "15M", "30M", "60M", "DAY", "WEEK", "MON", "QUARTER", "YEAR"]
        self.ui.stockTradingIntervalValue.clear()
        self.ui.stockTradingIntervalValue.addItems(time_interval_list)

        # Stock Trading Table - Stock List Display
        stock_list = json.loads(config.get('TradePreference', 'StockList'))
        if not stock_list:
            # Directly get list of stock codes from the data folder. Easier.
            stock_list = [str(f.path).replace('./data/', '') for f in os.scandir("./data/") if f.is_dir()]
            stock_list = stock_list[:-1]

        self.ui.stockTradingTable.clearContents()
        self.ui.stockTradingTable.setRowCount(0)

        equity_info_full = HKEXInterface.get_equity_info_full()
        assert equity_info_full
        headers = equity_info_full[0].keys()
        self.ui.stockTradingTable.setColumnCount(len(headers))
        self.ui.stockTradingTable.setHorizontalHeaderLabels(headers)
        # Bug from https://stackoverflow.com/questions/16619458/qt-table-widget-vertical-horizontal-header-becoming-invisible
        self.ui.stockTradingTable.horizontalHeader().setVisible(True)
        self.ui.stockTradingTable.verticalHeader().setVisible(False)

        for stock in equity_info_full:
            if stock["Stock Code"] in stock_list:
                row_number = self.ui.stockTradingTable.rowCount()
                self.ui.stockTradingTable.insertRow(row_number)
                for column_number, column_name in enumerate(headers):
                    self.ui.stockTradingTable.setItem(row_number, column_number, QTableWidgetItem(stock[column_name]))

        self.ui.stockTradingTable.resizeColumnsToContents()

        # Stock Trading Account Info Display
        account_info = futu_trade.get_account_info()
        self.ui.stockTradingNetAssetValue.setText(account_info['Net Assets'])
        self.ui.stockTradingPLValue.setText(account_info['P/L'])
        self.ui.stockTradingSecuritiesValueValue.setText(account_info['Securities Value'])
        self.ui.stockTradingCashValue.setText(account_info['Cash'])
        self.ui.stockTradingBuyingPowerValue.setText(account_info['Buying Power'])
        self.ui.stockTradingShortSellPowerValue.setText(account_info['Short Sell Power'])
        self.ui.stockTradingLMVValue.setText(account_info['LMV'])
        self.ui.stockTradingSMVValue.setText(account_info['SMV'])
        self.ui.stockTradingAvailableBalanceValue.setText(account_info['Available Balance'])
        self.ui.stockTradingMaxWithdrawlValue.setText(account_info['Maximum Withdrawal'])

        # Stock Trading Chart
        plot = pg.PlotWidget()
        self.ui.stockTradingChart.addWidget(plot)

    def __setThemeHack(self):
        Settings.BTN_LEFT_BOX_COLOR = "background-color: #495474;"
        Settings.BTN_RIGHT_BOX_COLOR = "background-color: #495474;"
        Settings.MENU_SELECTED_STYLESHEET = MENU_SELECTED_STYLESHEET = """
        border-left: 22px solid qlineargradient(spread:pad, x1:0.034, y1:0, x2:0.216, y2:0, stop:0.499 rgba(255, 121, 198, 255), stop:0.5 rgba(85, 170, 255, 0));
        background-color: #566388;
        """

        # SET MANUAL STYLES
        self.ui.lineEdit.setStyleSheet("background-color: #6272a4;")
        self.ui.pushButton.setStyleSheet("background-color: #6272a4;")
        self.ui.plainTextEdit.setStyleSheet("background-color: #6272a4;")
        self.ui.tableWidget.setStyleSheet(
            "QScrollBar:vertical { background: #6272a4; } QScrollBar:horizontal { background: #6272a4; }")
        self.ui.scrollArea.setStyleSheet(
            "QScrollBar:vertical { background: #6272a4; } QScrollBar:horizontal { background: #6272a4; }")
        self.ui.comboBox.setStyleSheet("background-color: #6272a4;")
        self.ui.horizontalScrollBar.setStyleSheet("background-color: #6272a4;")
        self.ui.verticalScrollBar.setStyleSheet("background-color: #6272a4;")
        self.ui.commandLinkButton.setStyleSheet("color: #ff79c6;")

    def __open_url(self, url):
        webbrowser.open(url)

    def __open_file(self, filters: str):
        path = QFileDialog.getOpenFileName(self, 'Open file', '', filters)
        if path != ('', ''):
            return path[0]

    @staticmethod
    def __create_message_box(title, text) -> QMessageBox:
        msgBox = QMessageBox()
        msgBox.setWindowTitle(title)
        msgBox.setWindowIcon(QtGui.QIcon(APP_LOGO_SMALL))
        msgBox.setIconPixmap(QtGui.QPixmap(APP_LOGO_SMALL))
        msgBox.setStyleSheet(Settings.MESSAGEBOX_STYLESHEET)
        msgBox.setText(text)
        msgBox.setStandardButtons(QMessageBox.Ok)
        msgBox.setWindowFlag(Qt.FramelessWindowHint)
        return msgBox

    def button_click_handler(self):
        # GET BUTTON CLICKED
        btn = self.sender()
        btnName = btn.objectName()

        # SHOW HOME PAGE
        if btnName == "btn_home":
            self.ui.stackedWidget.setCurrentWidget(self.ui.home)
            self.resetStyle(btnName)
            btn.setStyleSheet(self.selectMenu(btn.styleSheet()))
            return

        # SHOW SETTINGS PAGE
        if btnName == "btn_settings":
            self.ui.stackedWidget.setCurrentWidget(self.ui.settings)  # SET PAGE
            self.resetStyle(btnName)  # RESET ANOTHERS BUTTONS SELECTED
            btn.setStyleSheet(self.selectMenu(btn.styleSheet()))  # SELECT MENU
            return

        if config is None or stock_strategy_map is None:
            msgBox = self.__create_message_box("MISSING TRADING CONFIGURATION",
                                               "Please specify Configuration File and Stock Mapping first. ")
            msgBox.exec_()
            return

        # SHOW WIDGETS PAGE
        if btnName == "btn_widgets":
            self.ui.stackedWidget.setCurrentWidget(self.ui.widgets)
            self.resetStyle(btnName)
            btn.setStyleSheet(self.selectMenu(btn.styleSheet()))
            return

        # SHOW STOCK TRADING PAGE
        if btnName == "btn_stock_trading":
            self.__initialize_stock_trading_values()
            self.ui.stackedWidget.setCurrentWidget(self.ui.stock_trading)  # SET PAGE
            self.resetStyle(btnName)  # RESET ANOTHERS BUTTONS SELECTED
            btn.setStyleSheet(self.selectMenu(btn.styleSheet()))  # SELECT MENU
            return

    def resizeEvent(self, event):
        # Update Size Grips
        self.resize_grips()

    def mousePressEvent(self, event):
        # SET DRAG POS WINDOW
        self.dragPos = event.globalPos()

        # PRINT MOUSE EVENTS
        if event.buttons() == Qt.LeftButton:
            print('Mouse click: LEFT CLICK')
        if event.buttons() == Qt.RightButton:
            print('Mouse click: RIGHT CLICK')

    def maximize_restore(self):
        global GLOBAL_STATE
        status = GLOBAL_STATE
        if status == False:
            self.showMaximized()
            GLOBAL_STATE = True
            self.ui.maximizeRestoreAppBtn.setToolTip("Restore")
            self.ui.maximizeRestoreAppBtn.setIcon(QIcon(u":/icons/images/icons/icon_restore.png"))
            self.ui.frame_size_grip.hide()
            self.left_grip.hide()
            self.right_grip.hide()
            self.top_grip.hide()
            self.bottom_grip.hide()
        else:
            GLOBAL_STATE = False
            self.showNormal()
            self.resize(self.width() + 1, self.height() + 1)
            self.ui.maximizeRestoreAppBtn.setToolTip("Maximize")
            self.ui.maximizeRestoreAppBtn.setIcon(QIcon(u":/icons/images/icons/icon_maximize.png"))
            self.ui.frame_size_grip.show()
            self.left_grip.show()
            self.right_grip.show()
            self.top_grip.show()
            self.bottom_grip.show()

    # RETURN STATUS
    def returStatus(self):
        return GLOBAL_STATE

    # SET STATUS
    def setStatus(self, status):
        global GLOBAL_STATE
        GLOBAL_STATE = status

    # TOGGLE MENU
    def toggleMenu(self, enable):
        if enable:
            # GET WIDTH
            width = self.ui.leftMenuBg.width()
            maxExtend = Settings.MENU_WIDTH
            standard = 60

            # SET MAX WIDTH
            if width == 60:
                widthExtended = maxExtend
            else:
                widthExtended = standard

            # ANIMATION
            self.animation = QPropertyAnimation(self.ui.leftMenuBg, b"minimumWidth")
            self.animation.setDuration(Settings.TIME_ANIMATION)
            self.animation.setStartValue(width)
            self.animation.setEndValue(widthExtended)
            self.animation.setEasingCurve(QEasingCurve.InOutQuart)
            self.animation.start()

    # TOGGLE LEFT BOX
    def toggleLeftBox(self, enable):
        if enable:
            # GET WIDTH
            width = self.ui.extraLeftBox.width()
            widthRightBox = self.ui.extraRightBox.width()
            maxExtend = Settings.LEFT_BOX_WIDTH
            color = Settings.BTN_LEFT_BOX_COLOR
            standard = 0

            # GET BTN STYLE
            style = self.ui.toggleLeftBox.styleSheet()

            # SET MAX WIDTH
            if width == 0:
                widthExtended = maxExtend
                # SELECT BTN
                self.ui.toggleLeftBox.setStyleSheet(style + color)
                if widthRightBox != 0:
                    style = self.ui.settingsTopBtn.styleSheet()
                    self.ui.settingsTopBtn.setStyleSheet(style.replace(Settings.BTN_RIGHT_BOX_COLOR, ''))
            else:
                widthExtended = standard
                # RESET BTN
                self.ui.toggleLeftBox.setStyleSheet(style.replace(color, ''))

        self.start_box_animation(width, widthRightBox, "left")

    # TOGGLE RIGHT BOX
    def toggleRightBox(self, enable):
        if enable:
            # GET WIDTH
            width = self.ui.extraRightBox.width()
            widthLeftBox = self.ui.extraLeftBox.width()
            maxExtend = Settings.RIGHT_BOX_WIDTH
            color = Settings.BTN_RIGHT_BOX_COLOR
            standard = 0

            # GET BTN STYLE
            style = self.ui.settingsTopBtn.styleSheet()

            # SET MAX WIDTH
            if width == 0:
                widthExtended = maxExtend
                # SELECT BTN
                self.ui.settingsTopBtn.setStyleSheet(style + color)
                if widthLeftBox != 0:
                    style = self.ui.toggleLeftBox.styleSheet()
                    self.ui.toggleLeftBox.setStyleSheet(style.replace(Settings.BTN_LEFT_BOX_COLOR, ''))
            else:
                widthExtended = standard
                # RESET BTN
                self.ui.settingsTopBtn.setStyleSheet(style.replace(color, ''))

            self.start_box_animation(widthLeftBox, width, "right")

    def start_box_animation(self, left_box_width, right_box_width, direction):
        right_width = 0
        left_width = 0

        # Check values
        if left_box_width == 0 and direction == "left":
            left_width = 240
        else:
            left_width = 0
        # Check values
        if right_box_width == 0 and direction == "right":
            right_width = 240
        else:
            right_width = 0

            # ANIMATION LEFT BOX
        self.left_box = QPropertyAnimation(self.ui.extraLeftBox, b"minimumWidth")
        self.left_box.setDuration(Settings.TIME_ANIMATION)
        self.left_box.setStartValue(left_box_width)
        self.left_box.setEndValue(left_width)
        self.left_box.setEasingCurve(QEasingCurve.InOutQuart)

        # ANIMATION RIGHT BOX
        self.right_box = QPropertyAnimation(self.ui.extraRightBox, b"minimumWidth")
        self.right_box.setDuration(Settings.TIME_ANIMATION)
        self.right_box.setStartValue(right_box_width)
        self.right_box.setEndValue(right_width)
        self.right_box.setEasingCurve(QEasingCurve.InOutQuart)

        # GROUP ANIMATION
        self.group = QParallelAnimationGroup()
        self.group.addAnimation(self.left_box)
        self.group.addAnimation(self.right_box)
        self.group.start()

    # SELECT
    def selectMenu(self, getStyle):
        select = getStyle + Settings.MENU_SELECTED_STYLESHEET
        return select

    # DESELECT
    def deselectMenu(self, getStyle):
        deselect = getStyle.replace(Settings.MENU_SELECTED_STYLESHEET, "")
        return deselect

    # START SELECTION
    def selectStandardMenu(self, widget):
        for w in self.ui.topMenu.findChildren(QPushButton):
            if w.objectName() == widget:
                w.setStyleSheet(self.selectMenu(w.styleSheet()))

    # RESET SELECTION
    def resetStyle(self, widget):
        for w in self.ui.topMenu.findChildren(QPushButton):
            if w.objectName() != widget:
                w.setStyleSheet(self.deselectMenu(w.styleSheet()))

    # IMPORT THEMES FILES QSS/CSS
    def theme(self, file, useCustomTheme):
        if useCustomTheme:
            str = open(file, 'r').read()
            self.ui.styleSheet.setStyleSheet(str)

    # START - GUI DEFINITIONS
    def uiDefinitions(self):
        def dobleClickMaximizeRestore(event):
            # IF DOUBLE CLICK CHANGE STATUS
            if event.type() == QEvent.MouseButtonDblClick:
                QTimer.singleShot(250, lambda: self.maximize_restore())

        self.ui.titleRightInfo.mouseDoubleClickEvent = dobleClickMaximizeRestore

        if Settings.ENABLE_CUSTOM_TITLE_BAR:
            # STANDARD TITLE BAR
            self.setWindowFlags(Qt.FramelessWindowHint)
            self.setAttribute(Qt.WA_TranslucentBackground)

            # MOVE WINDOW / MAXIMIZE / RESTORE
            def moveWindow(event):
                # IF MAXIMIZED CHANGE TO NORMAL
                if self.returStatus():
                    self.maximize_restore()
                # MOVE WINDOW
                if event.buttons() == Qt.LeftButton:
                    self.move(self.pos() + event.globalPos() - self.dragPos)
                    self.dragPos = event.globalPos()
                    event.accept()

            self.ui.titleRightInfo.mouseMoveEvent = moveWindow

            # CUSTOM GRIPS
            self.left_grip = CustomGrip(self, Qt.LeftEdge, True)
            self.right_grip = CustomGrip(self, Qt.RightEdge, True)
            self.top_grip = CustomGrip(self, Qt.TopEdge, True)
            self.bottom_grip = CustomGrip(self, Qt.BottomEdge, True)

        else:
            self.ui.appMargins.setContentsMargins(0, 0, 0, 0)
            self.ui.minimizeAppBtn.hide()
            self.ui.maximizeRestoreAppBtn.hide()
            self.ui.closeAppBtn.hide()
            self.ui.frame_size_grip.hide()

        # DROP SHADOW
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(17)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(0)
        self.shadow.setColor(QColor(0, 0, 0, 150))
        self.ui.bgApp.setGraphicsEffect(self.shadow)

        # RESIZE WINDOW
        self.sizegrip = QSizeGrip(self.ui.frame_size_grip)
        self.sizegrip.setStyleSheet("width: 20px; height: 20px; margin 0px; padding: 0px;")

        # MINIMIZE
        self.ui.minimizeAppBtn.clicked.connect(lambda: self.showMinimized())

        # MAXIMIZE/RESTORE
        self.ui.maximizeRestoreAppBtn.clicked.connect(lambda: self.maximize_restore())

        # CLOSE APPLICATION
        self.ui.closeAppBtn.clicked.connect(lambda: self.exit_app())

    def exit_app(self):
        global futu_trade
        del futu_trade
        self.close()

    def resize_grips(self):
        if Settings.ENABLE_CUSTOM_TITLE_BAR:
            self.left_grip.setGeometry(0, 10, 10, self.height())
            self.right_grip.setGeometry(self.width() - 10, 10, 10, self.height())
            self.top_grip.setGeometry(0, 0, self.width(), 10)
            self.bottom_grip.setGeometry(0, self.height() - 10, self.width(), 10)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon("icon.ico"))
    window = SplashScreen()
    sys.exit(app.exec_())
