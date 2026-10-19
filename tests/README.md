# 测试

运行 `python -m unittest discover -s tests -v`。测试使用标准库 unittest，GUI 图像测试需要 Pillow，真实窗口测试需要 Tk 和显示服务。

`fixtures/round1` 与 `expected/round1.json` 是经过字段白名单整理的 121 条冻结观察。断言覆盖变量展开、作用域、参数、循环、输入字节、批处理跳转和重定向，保留精确输出与文件摘要。`fixtures/native-*.json` 包含 38 条独立宏展开和管道观察，脚本 SHA-256 用于防止 fixture 意外改变。

其他测试在临时目录构造最小脚本，验证解释器行为，而非某个外部应用的业务逻辑。真实终端和 GUI 测试按平台能力跳过，不能把跳过视为已经验证。原始主机观察报告与收集器归档校验不属于此公开测试集。
