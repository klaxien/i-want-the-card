# i-want-the-card

A tool to help user analyze possibility of getting a credit card

## 打包

windows
```
pyinstaller run.py --name "NiTanPreapproval" --onefile --windowed `
--icon=resources\icon-windows.ico `
--add-data "config.yaml;." `
--add-data "prompt_template.md;."
```

mac
```
pyinstaller --name "NiTanPreapproval" \
  --windowed \
  --icon resources/icon-mac.icns \
  --add-data "config.yaml:." \
  --add-data "prompt_template.md:." \
  run.py
```