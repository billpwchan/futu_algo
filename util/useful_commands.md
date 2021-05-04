
# GUI-Related Commands

**Update Customized Images in GUI**

Update resources.qrc using Qt Creator to add new files to the .qrc file. Then use the following command to update resources_rc.py file so that ui_main.py can import it later.
```python
pyside6-rcc icons.rc -o rc_icons.py