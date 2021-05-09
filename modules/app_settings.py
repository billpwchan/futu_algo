#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

class Settings():
    # APP SETTINGS
    ENABLE_CUSTOM_TITLE_BAR = True
    MENU_WIDTH = 240
    LEFT_BOX_WIDTH = 240
    RIGHT_BOX_WIDTH = 240
    TIME_ANIMATION = 500

    # BTNS LEFT AND RIGHT BOX COLORS
    BTN_LEFT_BOX_COLOR = "background-color: rgb(44, 49, 58);"
    BTN_RIGHT_BOX_COLOR = "background-color: #ff79c6;"

    # MENU SELECTED STYLESHEET
    MENU_SELECTED_STYLESHEET = """
    border-left: 22px solid qlineargradient(spread:pad, x1:0.034, y1:0, x2:0.216, y2:0, stop:0.499 rgba(255, 121, 198, 255), stop:0.5 rgba(85, 170, 255, 0));
    background-color: rgb(40, 44, 52);
    """

    MESSAGEBOX_STYLESHEET = """
        QMessageBox {
          font-family: 'Segoe UI', 'Open Sans', sans-serif;
          color: hsl(220, 50%, 90%);
          background: hsl(220, 25%, 10%);
          border-radius: 5px;
          padding: 5px;
        }
        QMessageBox QLabel {
            color: rgb(189, 147, 249);
            font: 10pt "Segoe UI"; 
            margin: 5px;
            padding: 5px;
            padding-left: 0px;
            text-align: center;
        }
        QMessageBox QPushButton {
            width: 60px;
            border: 2px solid rgb(52, 59, 72);
            border-radius: 5px;	
            background-color: rgb(52, 59, 72);
            background: linear-gradient(to right, hsl(210, 30%, 20%), hsl(255, 30%, 25%));
            color: rgb(255, 255, 255);
        }
        QMessageBox QPushButton:hover {
            background-color: rgb(57, 65, 80);
            border: 2px solid rgb(61, 70, 86);
        }
        QMessageBox QPushButton:pressed {	
            background-color: rgb(35, 40, 49);
            border: 2px solid rgb(43, 50, 61);
        }
        """
