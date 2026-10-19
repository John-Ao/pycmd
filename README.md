# pycmd

用 Python 实现的 Windows CMD / BAT 兼容解释器，支持变量展开、批处理调用、条件、循环、管道、重定向和常用文件命令。要求 Python 3.10+，核心无需第三方运行时依赖。

分发包名为 `wincmd`，导入包和命令名均为 `pycmd`。

## 安装与运行

在源码目录安装：

```sh
python -m pip install .
pycmd -c "echo hello"
pycmd --batch examples/countdown.bat
python -m pycmd --help
```

不传命令或脚本时进入交互模式。外部程序执行需显式添加 `--allow-external`。解释器会按脚本执行文件操作，不是沙箱，只应运行可信脚本。

POSIX CLI 默认使用 UTF-8；旧 GBK 脚本可用 `--codepage 936`。`--delayed` 开启延迟展开，`--traceback` 显示批处理调用栈，`--max-steps` 和 `--timeout` 可约束执行。`--xp` 提供旧式中文控制台字符宽度适配。

可选 Tk 图形控制台：

```sh
python -m pip install '.[gui]'
pycmd --gui --fontsize 20 --batch examples/countdown.bat
```

GUI 需要宿主安装 Tk 和可用的图形显示。Pillow 由 `gui` 扩展安装。支持文字、图片层、鼠标和滚动历史；窗口尺寸、终端输入和字体效果依赖宿主。

## Python API

```python
from pycmd import Runtime

runtime = Runtime(env={"VALUE": "hello"})
status = runtime.command("echo %VALUE%")
output = runtime.streams.table[1].getvalue()
assert status == 0
assert output == b"hello\r\n"
```

兼容范围包括 CMD 常用语法及部分外部工具适配。系统查询使用虚拟兼容值，部分环境依赖命令只实现基础行为；不保证所有 Windows 脚本或所有宿主下逐字节兼容。内置帮助是项目自行编写的简明说明。

## 开发与验证

```sh
python -m pip install -e '.[dev,gui]'
python -m unittest discover -s tests -v
python -m pycmd.replay --round all --all
python tools/check_public_tree.py
python tools/build_release.py
python -m twine check dist/*
```

无图形显示时，需真实窗口的测试会跳过。Linux 可用 `xvfb-run -a python -m unittest discover -s tests -v` 验证 GUI。发布包中的解释器不依赖测试数据；回放工具需要源码目录中的 `tests`，可通过 `--data-dir` 指定。

公开测试保留独立行为断言和精选的冻结输出，不包含原始机器采集记录或第三方应用源码。详见 [测试说明](tests/README.md)、[公开化整理说明](docs/public-release.md) 和 [发布步骤](docs/releasing.md)。

## 许可

[MIT](LICENSE)。
