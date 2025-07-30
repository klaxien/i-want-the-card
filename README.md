# i-want-the-card


## 打包

windows
```
pyinstaller --name "NiTanPreapproval" ^
  --onefile ^
  --add-data "config.yaml;." ^
  --add-data "prompt_template.md;." ^
  run.py
```

mac
```
pyinstaller --name "NiTanPreapproval" \
  --onefile \
  --add-data "config.yaml:." \
  --add-data "prompt_template.md:." \
  run.py
```