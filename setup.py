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


import sys
import os
from cx_Freeze import setup, Executable
import pkg_resources

# ADD FILES
files = ['icon.ico', 'themes/', 'stock_strategy_map_template.yml', 'config_template.ini']

# TARGET
target = Executable(
    script="main.py",
    base="Win32GUI",
    icon="icon.ico",
    target_name="futu-algo.exe"
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
