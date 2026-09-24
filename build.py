from tomllib import load
from argparse import ArgumentParser
from subprocess import run

with open("pyproject.toml", "rb") as file:
    version = load(file)["project"]["version"]

parser = ArgumentParser(description="打包摩尔抓包工具")
parser.add_argument("--dir", default="D:\\Downloads", help="输出目录（默认：D:\\Downloads）")
parser.add_argument("--file", default="mole.exe", help="输出文件名（默认：mole.exe）")
args = parser.parse_args()

cmd = " ".join([
    "nuitka", "mole.py",
    "--standalone", "--jobs=8", "--lto=yes", "--remove-output",
    "--windows-console-mode=disable", "--windows-icon-from-ico=icon.ico",
    "--enable-plugin=pyside6",
    "--copyright=\"Copyright (C) 2025 lingcraft. All Rights Reserved\"",
    "--file-description=摩尔抓包工具",
    "--product-name=摩尔抓包工具",
    f"--file-version={version}",
    f"--product-version={version}",
    f"--output-dir=\"{args.dir}\"",
    f"--output-filename={args.file}",
    "--include-package-data=pypinyin",
    "--include-data-files=hook.dll=hook.dll",
    "--include-data-files=pyproject.toml=pyproject.toml",
    "--include-data-files=github.ico=github.ico",
    "--include-data-files=Flash.ocx=Flash.ocx",
    "--include-data-files=manifest=manifest",
    "--include-data-files=zh_CN.qm=zh_CN.qm",
    "--include-data-dir=swf=swf",
    "--onefile"
])

run(cmd, input=b"Yes\n", shell=True)
