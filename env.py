from datetime import datetime
from hashlib import md5
from os import environ
from tomllib import load

with open("pyproject.toml", "rb") as file:
    project = load(file)["project"]

with open("deps.hash", "w") as file:
    file.write(md5(str(sorted(project["dependencies"])).encode()).hexdigest())

with open(environ["GITHUB_ENV"], "a", encoding="utf-8") as env:
    env.write(f"""\
VERSION={project["version"]}
DESCRIPTION<<EOF
{project["description"].strip()}
EOF
NUITKA_PATH={environ["localappdata"]}\\Nuitka\\Nuitka\\Cache
WEEK={datetime.now().strftime("%V")}
""")
