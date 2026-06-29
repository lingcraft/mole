$version = $(python -c "from tomllib import load; print(load(open('pyproject.toml','rb')).get('project').get('version'))").Trim()
Write-Output "Yes" | uv run nuitka mole.py --standalone --jobs=8 --lto=yes --remove-output `
--windows-console-mode=disable --windows-icon-from-ico=icon.ico --enable-plugin=pyside6 `
--copyright="Copyright (C) 2025 lingcraft. All Rights Reserved" `
--file-description=摩尔抓包工具 `
--product-name=摩尔抓包工具 `
--file-version=$version `
--product-version=$version `
--output-dir=D:\Downloads `
--output-filename=mole.exe `
--include-package-data=pypinyin `
--include-data-files=hook.dll=hook.dll `
--include-data-files=pyproject.toml=pyproject.toml `
--include-data-files=github.ico=github.ico `
--include-data-files=Flash.ocx=Flash.ocx `
--include-data-files=manifest=manifest `
--include-data-files=zh_CN.qm=zh_CN.qm `
--onefile