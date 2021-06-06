#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *


class PyToggle(QCheckBox):
    def __init__(
            self,
            width=60,
            bg_color="#777",
            circle_color="#DDD",
            active_color="#00BCff",
            animation_curve=QEasingCurve.OutBounce
    ):
        QCheckBox.__init__(self)

        # SET DEFAULT PARAMETERS
        self.setFixedSize(width, 28)
        self.setCursor(Qt.PointingHandCursor)

        # COLORS
        self._bg_color = bg_color
        self._circle_color = circle_color
        self._active_color = active_color

        # CREATE ANIMATION
        self._circle_position = 3
        self.animation = QPropertyAnimation(self, b"circle_position", self)
        self.animation.setEasingCurve(animation_curve)
        self.animation.setDuration(500)  # Time in milisseconds

        # CONNECT STATE CHANGED
        self.stateChanged.connect(self.start_transition)

    # CREATE NEW SETTER AND GET PROPERTIE
    @Property(float)  # Get
    def circle_position(self):
        return self._circle_position

    @circle_position.setter  # Setter
    def circle_position(self, pos):
        self._circle_position = pos
        self.update()

    # START ANIMATION
    def start_transition(self, value):
        self.animation.stop()  # Stop animation if running
        if value:
            self.animation.setEndValue(self.width() - 26)
        else:
            self.animation.setEndValue(3)

        # START ANIMATION
        self.animation.start()

    # SET NEW HIT AREA
    def hitButton(self, pos: QPoint):
        return self.contentsRect().contains(pos)

    # DRAW NEW ITEMS
    def paintEvent(self, e):
        # SET PAINTER
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # SET AS NO PEN
        p.setPen(Qt.NoPen)

        # DRAW RECTANGLE
        rect = QRect(0, 0, self.width(), self.height())

        # CHECK IF IS CHECKED
        if not self.isChecked():
            # DRAW BG
            p.setBrush(QColor(self._bg_color))
            p.drawRoundedRect(0, 0, rect.width(), rect.height(), rect.height() // 2, rect.height() // 2)

            # DRAW CIRCLE
            p.setBrush(QColor(self._circle_color))
            p.drawEllipse(self._circle_position, 3, 22, 22)
        else:
            # DRAW BG
            p.setBrush(QColor(self._active_color))
            p.drawRoundedRect(0, 0, rect.width(), rect.height(), rect.height() // 2, rect.height() // 2)

            # DRAW CIRCLE
            p.setBrush(QColor(self._circle_color))
            p.drawEllipse(self._circle_position, 3, 22, 22)

        # END DRAW
        p.end()
