# 六模型完整脚本与缓存审阅入口

更新日期：2026-09-14。用途是把原评测实现交给同事检查，并对照原始证据核查是否因跨轮缓存残留高估 SLA TPM。不是新的测试结果，也没有修改任何线上或本地服务。

**后续修正说明**：下述快照/缓存审计仍是历史记录。用户随后用标准 benchmark 复现 V4 Flash 超限；新入口为[standard_sla.py](../scripts/standard_sla.py)，标准首非空文本 TTFT 与首 token 诊断分列、指数到达、精确数据/前缀隔离。缓存审计通过不能排除到达分布、输入重分词和计时差异，也不能把旧0.358秒当作标准 benchmark 同口径结果。原始源码快照及结果不改写。

## 修正后 V4 Flash 复现入口

仓库内提供 [客户端](../scripts/bench_v4_flash_sla_corrected.sh)、[服务端](../scripts/start_v4_flash_0731_tp2.sh) 和相邻的 [standard_sla.py](../scripts/standard_sla.py)。以下相对命令从本 skill 根目录执行。

客户端会从 `.sh` 自身所在目录调用 `standard_sla.py`，不再固定写死 `/volume/dev/alan/skill-repo`。Python/runtime 默认仍使用原机器提取的固定镜像目录；`SGL_SLA_CLIENT_RUNTIME` 可指定另一份同版本 runtime 根目录，目录下须有 `opt/sglang/bin/python` 与 `sgl-workspace/sglang/python`。不要不经核对切换客户端版本；被动观测的 AST 锚点和代码哈希用于发现运行时变化。

本仓库**不包含**模型权重、CUDA/Python runtime、原始 `input_ids.npz` 或完整请求/引擎日志。客户端即使离线检查也需要本地数据：`--reference-point` 所指目录必须包含 `manifest.json`、`initial-server-info.json` 和 `input_ids.npz`，其中模型/tokenizer 路径必须在本机有效；输入数组哈希及前缀边界要通过校验。`gsp-text` 仅为原机器特定 GSP 缓存的诊断入口，不是跨机器自动构造任意数据的模式。

只做离线检查（不启动模型、不发请求、不清缓存）：

```bash
bash scripts/start_v4_flash_0731_tp2.sh --dry-run
bash scripts/bench_v4_flash_sla_corrected.sh --dry-run --request-rate 2.5
```

获得本地执行授权、确认 GPU 0/1 和端口 30480/30580 空闲后，先在独立终端启动服务：

```bash
bash scripts/start_v4_flash_0731_tp2.sh >> /tmp/v4flash-0731-tp2.log 2>&1
```

服务端为前台进程，保留原 H200×2 / TP2、DSPARK、FP8 KV、mem=.906、decode graph256 配置；它不会停止已有服务。日志使用文件，避免终端输出无人读取造成 HTTP 日志写入阻塞。不要为了查看日志而读取服务进程的 TTY 文件描述符。

服务就绪并确认实例独占且空闲后，再运行客户端：

```bash
bash scripts/bench_v4_flash_sla_corrected.sh --execute --request-rate 2.5
```

这是一个 200 条固定数据的单速率点，不是宣称 2.5 RPS 满足 SLA。每点先 flush、验证冷预置，再只复用公共前缀；输出包含原生 TTFT/TPOT、首 token 诊断、实际缓存率、引擎代次及逐请求证据。其他模型须提供各自的 reference、SLA 参数及原部署，不能直接沿用 V4 Flash 默认值。

2026-09-14 后续重测已按用户要求跳过 V4.1，只测其余五项，部署保持历史实际配置，按标准随机到达重新搜索；旧等间隔结果不作为新通过证据。本次发布没有附带正在运行的自动队列或实时 PID 状态，也不触发、暂停或重启已有测试。

发布前再次验证：49 个冻结文件的哈希/语法、skill 格式、两个 shell 的语法及离线 dry-run 均通过；缓存审计 6 项与原生计时/前缀验证 7 项合计 13 项测试通过。客户端也从仓库外工作目录完成离线检查。发布检查没有发出服务请求，也没有重新执行任何历史压测队列。

## 交付范围与版本

原文件逐字节放在 `scripts/snapshot-20260914/`，索引为 [SOURCES.json](../scripts/snapshot-20260914/SOURCES.json)，共 40 个 Python 文件、9 个配置/历史策略 JSON。包括原五模型项目和 GLM 5.3 NVFP4 项目顶层的全部 Python 文件、价格/部署配置、相关历史调参及策略记录，以及它们复用的三个本地 Python 辅助文件。没有把两个不同发压版本拼成新脚本。

- 前五模型以及 NVFP4 最早的固定 200 条执行核心：SHA-256 `98806c6426b44c51c384cb85cfc75410b5d6dea835465c4a0e08d6457568abad`。
- NVFP4 后续支持首批 100 条检查的执行核心：SHA-256 `028ab6e65bc515480fa2441c3333316c0d356cfd728d537cd709ac740f1b629f`。
- 逐点 `manifest.json → client.script_sha256` 与以上版本对应。控制器、报告和辅助脚本是审阅时本地快照；并非每个历史执行阶段都保存过其哈希，不能把全部文件无条件称为当时唯一版本。
- 冻结脚本未修补：例如原发压器只断言 flush HTTP 200 和预置请求成功，没有在发压前主动断言预置 `cached_tokens == 0`。这是防护检查不足；是否真的漏清理，要看本轮日志、首次预置命中和正式请求，不能仅凭这个代码缺口认定历史结果失效。

## 从哪些文件开始看

下表中 `A` 指 `scripts/snapshot-20260914/five-model-cost-20260913/`；`B` 指 `scripts/snapshot-20260914/glm53-nvfp4-perf-20260914/`。

| 要检查的逻辑 | 文件 / 入口 | 关键问题 |
|---|---|---|
| 数据、warmup、flush、预置、发压、逐请求计量 | [A/benchmark.py](../scripts/snapshot-20260914/five-model-cost-20260913/benchmark.py)，`dataset / run / Stream.result` | 是否每轮清理；预置的是前缀还是完整 prompt；TPOT 是否按 token 而不是 SSE chunk 计数 |
| SLA 搜索、速率调整、停止条件 | [A/conduct.py](../scripts/snapshot-20260914/five-model-cost-20260913/conduct.py)，[A/run_model.py](../scripts/snapshot-20260914/five-model-cost-20260913/run_model.py) | 每个速率是否启动独立发压进程；延迟失败和运行异常是否分开 |
| V4 Pro 人工核验后的续测 | [A/reviewed_sla_probe.py](../scripts/snapshot-20260914/five-model-cost-20260913/reviewed_sla_probe.py) | 原通过/失败区间如何继承；当前引擎身份与资源复核 |
| 卡数、SLA、基础部署参数 | [A/profiles.json](../scripts/snapshot-20260914/five-model-cost-20260913/profiles.json)，[B/profiles.json](../scripts/snapshot-20260914/glm53-nvfp4-perf-20260914/profiles.json) | 实际点还要看该代 `launch.json` 的 argv/override，不能只看基础 profile |
| NVFP4 发压核心与观察包装 | [B/benchmark_core.py](../scripts/snapshot-20260914/glm53-nvfp4-perf-20260914/benchmark_core.py)，[B/benchmark.py](../scripts/snapshot-20260914/glm53-nvfp4-perf-20260914/benchmark.py) | 核心版本和 wrapper 的职责；是否混入健康探测、GPU 观察或其他请求 |
| NVFP4 提前检查与排空 | [B/adaptive_sampling.py](../scripts/snapshot-20260914/glm53-nvfp4-perf-20260914/adaptive_sampling.py)，[B/conduct.py](../scripts/snapshot-20260914/glm53-nvfp4-perf-20260914/conduct.py) | 首先完成的是前 100 个计划请求；只取消未发送任务；已发送全部排空后重新判定 |
| 原有计量交叉核对 | [A/audit_token_accounting.py](../scripts/snapshot-20260914/five-model-cost-20260913/audit_token_accounting.py)，[B/final_audit.py](../scripts/snapshot-20260914/glm53-nvfp4-perf-20260914/final_audit.py) | 请求 token 合计与服务端 counter 差值是否一致 |
| TPM / 峰谷价 / 月收入 / 六模型汇总 | [A/report_results.py](../scripts/snapshot-20260914/five-model-cost-20260913/report_results.py)，[A/summarize_campaign.py](../scripts/snapshot-20260914/five-model-cost-20260913/summarize_campaign.py)，[A/prices.json](../scripts/snapshot-20260914/five-model-cost-20260913/prices.json)，[B/report.py](../scripts/snapshot-20260914/glm53-nvfp4-perf-20260914/report.py) | 使用完成 token / 完整窗口；按真实卡数分摊；命中输入单独计价 |
| 启动、停止、续跑、运行环境 | `A/local_campaign.py`、`engine_lifecycle.py`、`official_runtime.py`、`run_remaining.py`；`B/experiment.py`、`launch_sla_search.py` | 这些入口会有副作用，只审阅，不作为审计命令执行 |

原有 `test_*.py` 一并保留。其中部分测试需要原机器 tokenizer、原始报告或运行证据；不能把缺少数据导致的测试失败认定为算法问题。依赖 `aiohttp`、`numpy`、`tokenizers`、`requests` 及各自固定的 SGLang/CUDA 环境；实际客户端版本见逐点 manifest。

## 原始每轮流程

```text
固定 seed，构建整轮 input_ids（公共前缀 + 每条独立尾部）
  → 128-token 无关短输入预热，16-token 输出
  → POST /flush_cache?timeout=30
  → 记录 HTTP/body；非 200 则停止
  → 仅预置最长公共前缀，生成 1 token；DP attention 时逐单元预置
  → 保存正式前 metrics
  → 独立 open-loop 正式请求，无客户端并发上限、无 retry
  → 等待已发送请求结束，保存正式后 metrics
  → 按逐请求实际 tokens、完整正式窗口计算 TPM / 均值 / 收入
```

正式轮间复用相同数据和 seed 是设计行为，因此必须清掉上一轮的完整 prompt。区别在于：**清缓存后仍会重新预置公共前缀**，正式开始不是全冷状态。计时不包括这个预置成本。

`flush.json` 的 HTTP 200 正文包含“运行或排队时可能不执行”的提示。离线审计同时看本轮 warmup 结束到 preseed 开始之间的 `Cache flushed successfully!`、首次预置 `cached_tokens=0`、正式逐请求缓存不超出其公共前缀长度、原始 NPZ/manifest 一致性及服务端计数器差值。

## 六模型范围及样本差异

| 模型 | H200 | 输入 / 输出 tokens | 目标 token 命中率 | 平均 TTFT 门槛 | 平均 TPOT 门槛 |
|---|---:|---:|---:|---:|---:|
| V4.1 Flash | 8 | 8,000 / 1,252 | 93.2% | <2 s | ≤20 ms |
| V4 Flash 0731 | 2 | 22,016 / 514 | 79.6% | ≤1 s | ≤25.4 ms |
| V4 Pro 0813 | 8 | 49,664 / 948 | 86.8% | ≤2.86 s | ≤22.2 ms |
| GLM 5.3 FP8 | 8 | 72,125 / 1,095 | 94.532% | ≤1.397 s | ≤1000/60 ms |
| GLM 5.3 Flash FP8 | 4 | 73,835 / 1,447 | 92.56% | ≤2 s | ≤1000/30 ms |
| GLM 5.3 NVFP4 | 8 | 72,125 / 1,095 | 94.532% | ≤1.397 s | ≤1000/60 ms |

前五模型正式点各 200 条。用户后来允许 NVFP4 首批 100 条均满足条件后停止新增提交、提高下一点速率；最高通过点为 119/119，另一点为 104/104，最终统计含当时所有在途请求，而不是只选最快 100 条。本次六模型范围不含后来的 GLM 5.3 Flash NVFP4 两卡实验。

NVFP4 是新增权重量化/部署变体，不是第六种官方 API 单价，使用 GLM 5.3 的同一价格情景。V4 Pro 纯吞吐缓存率超原容差后被用户接受的记录也保留，但此次只核对 SLA，不重评纯吞吐。

## 安全的离线检查命令

以下命令从 skill 根目录执行，不会访问服务。`verify_snapshot.py` 只计算哈希及解析语法；不要为检查而导入历史启动脚本。

```bash
python3 scripts/verify_snapshot.py
python3 -B -m unittest discover -s scripts -p 'test_audit_sla_cache.py' -v
```

如果就在原机器，可额外验证归档与原文件逐字节一致：

```bash
python3 scripts/verify_snapshot.py --source-root /volume/dev/alan/deployments
```

交付校验：49 个源文件与原件 SHA-256 一致，Python/JSON 语法和 skill 格式检查通过；新增审计测试 6 项、原五模型核心测试 8 项、NVFP4 核心测试 10 项，共 24 项通过。这些是离线测试，没有启动引擎或对服务发送请求。未执行依赖全部原始报告/硬件状态的所有历史测试，不能称为完整部署回归。

独立缓存审计需要 `numpy` 和原始证据目录。路径可换为同事机器上的证据副本，`--output` 必须不存在且不在输入目录内部；重复执行用新输出路径，不覆盖原记录。

```bash
python3 scripts/audit_sla_cache.py \
  --root /volume/dev/alan/deployments/five-model-cost-20260913 \
  --root /volume/dev/alan/deployments/glm53-nvfp4-perf-20260914 \
  --output /tmp/six-model-cache-review-new-run \
  --datasets all
```

每个 evidence root 需要 `benchmarks/*/{manifest,summary,flush,cache-preseed,warmup}.json`、`input_ids.npz`、`requests/*.json`、`metrics-{before,after}.txt`、`runs/<engine>/engine.log` 及执行源码。没有最终 summary 的尝试仍会列出。原始 NPZ、请求全文、完整日志、模型权重、运行时镜像和 live PID 状态没有复制进 skill，避免把巨量证据、生成内容或失效进程记录混入代码交付；已附审计输出保留逐点定位和元数据哈希，重新独立核对须取得上述原件。

## 2026-09-14 离线核对结论

详见 [审计表](../assets/cache-audit-20260914/AUDIT.md) 和 [逐点审计 JSON](../assets/cache-audit-20260914/audit.json)。

- 43 个 SLA 尝试点，40 个存在最终 summary；这 40 个全部通过缓存隔离/计量审计，覆盖 7,823 个正式请求。这里的“审计通过”不等于全部达到 SLA，原延迟失败点也保留。
- 其余 3 点：GLM Flash 中断后留下 5 条、NVFP4 中断后留下 4 条；V4 Pro 一次前缀预置失败、没有正式请求，均未纳入最终六模型 TPM。审计分别标 INCOMPLETE、INCOMPLETE、FAIL，不隐去异常。
- 用户表中的六个点均找到本轮清理成功日志，首次 preseed 命中为 0；没有正式请求命中超过构造公共前缀。全部 43 组 NPZ 哈希和公共前缀/独立尾部结构已核对。
- 没有发现这六个结果因“每轮忘记 flush，复用上轮完整 prompt 缓存”偏高的证据，因此未触发用户所说条件下的六模型 SLA 重测。

这不表示一定能对齐另一套压测。仍须比较：是否把前缀预置计入时长、单共享前缀与多前缀工作集、实际命中率、native `input_ids` 与 router/chat 接入、固定随机 token 与真实文本、MTP acceptance、输入输出分布，以及总 TPM 是否包含命中输入。不能只用同样的平均输入长度和目标缓存百分比认定负载相同。
