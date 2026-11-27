# QE SCF Slim 中文快速上手

拿到一批 Quantum ESPRESSO `pw.x` 输出后，可以先筛出需要重看的作业，再按行号回到原始日志。离线诊断只需要 Python 3.10 或更新版本，登录节点上没有安装 QE 也能用。

~~~sh
git clone https://github.com/xxs4661/qe-scf-slim.git
cd qe-scf-slim
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
scf-slim compare examples/si-*.out
scf-slim diagnose examples/si-maxstep.out
~~~

仓库里这两份硅计算的输出来自真实的 PWSCF 7.5。两份日志都有 `JOB DONE.`，电子收敛结果却不同。第一份在第 10 步收敛，最后报告的 SCF 精度估计小于 4.7×10⁻⁹ Ry。第二份把 `electron_maxstep` 限为 2，QE 明确报告未收敛。诊断会给出这条记录的行号。完整输入、赝势校验值和复现命令见[硅示例](examples/README.md)。

## 用在自己的作业上

~~~sh
scf-slim diagnose Si/scf.out.gz
scf-slim compare runs/*/scf.out
scf-slim compare --check --json runs/*/scf.out > batch.json
~~~

- 看单个作业时，`diagnose` 显示最近一次运行的结论、迭代步数、精度估计和原文证据。加 `--json` 能取出最后一个电子循环的逐步历史。
- 看一批作业时，`compare` 按输入顺序列出结果。加 `--check` 后，全部收敛返回 0，有作业未通过返回 1，文件读取或参数错误返回 2。
- 工具针对常规电子自洽计算。它能识别并标记多种超出范围的任务，包括能带、结构弛豫和分子动力学。电子收敛之后，材料性质仍需检查截断能和 k 点采样。

## 需要实际试算 mixing_beta 时

~~~sh
python -m pip install '.[probe]'
scf-slim probe --doctor
scf-slim probe --template silicon.in --outdir runs/si --dry-run
scf-slim probe --template silicon.in --outdir runs/si
~~~

实跑需要可用的 `pw.x` 和模板对应的赝势。建议先用 `--dry-run` 查看预算。默认以 1e-4 Ry 筛选候选值，再以 1e-8 Ry 做完整电子自洽验证。每次试算都保留输入和 stdout，验证状态写在推荐 JSON 中。命令、状态含义和配置入口见[英文说明](README.md)。
