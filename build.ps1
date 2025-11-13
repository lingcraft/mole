$version = (Get-Content -Path "version.json" -Raw | ConvertFrom-Json).version
Write-Output "Yes" | nuitka mole.py `
--standalone --windows-console-mode=disable --jobs=8 --lto=yes --remove-output `
--enable-plugin=pyside6 `
--windows-icon-from-ico=icon.ico `
--include-data-files=hook.dll=hook.dll `
--include-data-files=version.json=version.json `
--include-data-files=github.ico=github.ico `
--file-description=摩尔抓包工具 `
--product-name=摩尔抓包工具 `
--copyright="Copyright (C) 2025 lingcraft. All Rights Reserved" `
--file-version=$version `
--product-version=$version `
--onefile `
--output-filename=mole.exe `
--output-dir=D:\Downloads