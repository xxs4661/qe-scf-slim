# QE SCF Slim 中文快速上手

把一批 Quantum ESPRESSO `pw.x` 日志交给 `triage`，它会先列出需要干预的作业，再给出原因、原始行号和下一步动作。它只读已有输出，登录节点上有 Python 3.10 或更新版本即可，不会启动计算。

~~~sh
git clone https://github.com/xxs4661/qe-scf-slim.git
cd qe-scf-slim
python3 scripts/scf_slim/run_scf.py triage --all examples/
python3 scripts/scf_slim/run_scf.py diagnose examples/al111/beta-070.out
~~~

在虚拟环境中运行 `python -m pip install .` 后，就可以在任意目录使用 `scf-slim`。

| 判断 | 含义 | 典型动作 |
| --- | --- | --- |
| `intervene` 需要干预 | 日志记录了阻碍这次计算交付的具体问题 | 检查缺失的赝势、过低的迭代上限或反复回升的 SCF 精度估计 |
| `review` 需要核实 | 还缺上下文，或报告的数值值得复核 | 对照调度器判断任务是否仍在运行，或查看末几步的能带警告 |
| `none` 无需干预 | QE 报告电子自洽收敛且正常结束，规则未发现需要处理的问题 | 保留本次 SCF 结果，按物理量要求另行验证截断能和 k 点收敛 |

## 两组实算说明了什么

**硅晶体。** 一份日志在第 10 步收敛，另一份只允许 2 步就耗尽预算。两份都有 `JOB DONE.`。工具分别给出“保留结果”和“检查迭代上限”。这个例子中，直接用 QE 默认 β 跑了 8 步，而全套 β 搜索加验证一共跑了 99 步。[硅算例](examples/README.md) · [搜索成本记录](examples/si-search-cost.json)

**六层 Al(111) 金属表面。** 在同样的 40 步预算、1e-8 Ry 阈值、`plain` 混合和 `mixing_ndim=2` 下，β=0.70 的运行末段反复回升，40 步结束时仍未收敛。工具据此建议核对结构和占据设置，再做一次只降低 β 的重试。其他条件保持一致，改为 β=0.20 后，第 22 步收敛。把混合历史恢复为默认的 8 个向量后，两者都收敛，β=0.70 用 18 步，β=0.20 用 27 步。单份日志能提示值得验证的假设，成对实验才检验了此次更改的效果。[完整输入、日志、曲线和复现实验](examples/al111/README.md)

## 三轮实算的时间账

七个算例覆盖五种材料。每轮七个任务全部收敛时，统一先用 β=0.20 直接算的中位耗时为 57.64 秒，先用 β=0.70、失败后统一降 β 为 90.11 秒，按日志分诊后重试为 90.16 秒，两个 β 都跑一遍为 124.86 秒。分诊和失败后统一降 β 实际走了相同的求解路径，额外开销为每批 0.055 秒。五个新算例都直接收敛，唯一需要干预的物理算例是已知的短混合历史 Al(111)。两个单独设置的输入故障中，读对原因能避免无效重试。运行中能自行收敛的 Si、Fe 也触发过振荡提醒，直接按提醒杀任务会误停。[完整时间账、原始日志和复现步骤](benchmarks/scf-cost-panel/README.md)

## 用在自己的作业上

~~~sh
scf-slim triage /scratch/my-jobs
scf-slim triage --check --json /scratch/my-jobs > actions.json
scf-slim diagnose Si/scf.out.gz
scf-slim compare ref/scf.out retry/scf.out
~~~

`triage` 递归读取目录中的 `*.out` 与 `*.out.gz`，也接受其他文件名的显式路径或标准输入 `-`。默认文本只展开需要关注的作业，`--all` 也列出健康作业。JSON 记录每份日志的 `status`、干预优先级、原因、下一步和证据行号。`triage --check` 在全部无需干预时返回 0，有待干预或核实的作业时返回 1，输入或读取错误返回 2。`diagnose --check` 和 `compare --check` 仍按电子收敛状态判断。

如果确实需要搜索多个 β，可以显式调用 `probe`，先用 `--dry-run` 核对预算。常规作业先直接算，更换一个参数后按相同精度和资源比较两次结果。详细配置见[英文说明](README.md)。
