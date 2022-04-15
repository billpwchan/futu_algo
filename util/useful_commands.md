# GUI-Related Commands

**Update Customized Images in GUI**

Update resources.qrc using Qt Creator to add new files to the .qrc file. Then use the following command to update resources_rc.py file so that ui_main.py can import it later.
```python
pyside6-rcc resources.qrc -o ./modules/resources_rc.py
```

# Miscellaneous

**Freeze Conda Environment**
The best way to freeze the environment. Before freezing, better to clean unused packages in the environment.
```bash
conda clean --all --yes
conda env export > environment.yml
```

**Freeze Required Dependencies**

Update requirement.txt using the pipreqs library to generate pip-installed packages (NOT RECOMMENDED).

```bash
pipreqs ./ --encoding=utf-8 --force
```
