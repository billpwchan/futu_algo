#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

import sys
import os
from cx_Freeze import setup, Executable

# ADD FILES
files = ['icon.ico', 'themes/']

# TARGET
target = Executable(
    script="main.py",
    base="Win32GUI",
    icon="icon.ico"
)

# SETUP CX FREEZE
setup(
    name='Futu_Algo',
    version="1.0",
    description="FuTu Algorithmic Trading Tool for Everyone!",
    author='Bill Chan',
    author_email='billpwchan@hotmail.com',
    options={'build_exe': {'include_files': files}},
    executables=[target]

)
