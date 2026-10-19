# 发布步骤

仓库可上传 GitHub；分发名称为 `wincmd`。发布前需自行确认 PyPI 上该名称可用或账户有维护权限，并更新版本号。这里不预设个人账户、邮箱或仓库 URL。

```sh
python -m pip install -e '.[dev,gui]'
python -m unittest discover -s tests -v
python tools/check_public_tree.py
python tools/build_release.py
python -m twine check dist/*
```

构建后检查 wheel 与源码归档的文件清单。源码归档包含测试和合成 fixture，wheel 仅包含运行时包。实际上传前在干净虚拟环境中安装 wheel，并验证 `pycmd -c "echo hello"` 和 `pycmd -c "for /?"`。

可先上传 TestPyPI：

```sh
python -m twine upload --repository testpypi dist/*
```

确认后上传 PyPI：

```sh
python -m twine upload dist/*
```

凭据由发布者的凭据管理工具提供，禁止写入仓库。创建 GitHub 远程仓库后，按 GitHub 给出的现有仓库推送步骤设置远程并推送；本项目没有预置远程地址或自动上传工作流。
