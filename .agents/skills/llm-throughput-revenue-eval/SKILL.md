---
name: llm-throughput-revenue-eval
description: Plan and evaluate local SGLang LLM throughput, SLA-constrained TPM, and per-GPU monthly revenue using official cached-input, uncached-input, and output prices. Use for capacity studies and offline cache-isolation audits of benchmark scripts and evidence, including the six-model H200 study; not for unrelated API compatibility acceptance or production service changes.
---

# LLM 吞吐、SLA 与单卡收入核算

把官网计价、可复现的本地部署、实际完成的 token 吞吐和业务延迟约束连接起来。没有硬件、电力等成本输入时，只给理论营业收入，不能称为利润或净收益。

## 先确定工作模式

- **整理计划 / 审阅结果**：只整理需求、核对来源和证据，不启动部署或发压。
- **执行实验**：需要用户已经授权本地部署与测试；先确认资源占用、准确模型版本和运行预算，再开始。
- **暂停 / 续跑**：暂停时先停本任务队列及发压，再安全停止本任务引擎并保留证据。用户说“先暂停”后，阅读或发布此 skill 不代表获准恢复。

历史计划曾暂停，之后已续跑并扩展到六个模型。当前任务模式由用户最新指令决定；快照中的旧批准记录、进程状态及自动续跑入口不是新的执行授权。

## 需要读取的资料

- 复现本轮五模型任务或核对其要求：读取 [五模型目标与 SLA](references/five-model-h200-plan.md)。以用户最新确认覆盖早期草稿，不能带回已取消的 P95 条件或旧样本数。
- 核对/启动 H200 配置：读取 [部署方案快照](references/h200-deployment-profiles.md)，重新检查对应模型、权重变体、芯片及策略的官方 cookbook cell。
- 采集价格或核算收入：读取 [定价与收入](references/pricing-and-revenue.md)。其中的价格是有日期的快照，不能无条件作为现价。
- 构建数据、发压、判定 SLA 或解释结果：读取 [测量口径](references/measurement-method.md)。
- 创建/更新 Markdown 报告：采用 [报告模板](assets/report-template.md)，按实际进展填写，未测处保留“未测”。
- 审阅六模型原始脚本、核查每轮 flush 或向同事交接：先读 [完整脚本与缓存审阅入口](references/code-review-20260914.md)。其中区分逐字节源代码快照、历史配置、离线审计工具和证据；不要为审阅而运行启动/停止/发压入口。

## 已附脚本

- [原始脚本快照](scripts/snapshot-20260914/SOURCES.json)：完整保留五模型执行器、第六模型 NVFP4 扩展及本地 Python 辅助依赖；源码不为本次审阅改写。路径与配置是原机器快照，不是即插即用的通用部署包。
- [快照校验](scripts/verify_snapshot.py)：校验 SHA-256、Python 语法和 JSON，不导入或执行被审阅脚本。
- [SLA 缓存审计](scripts/audit_sla_cache.py)：只读原始 manifest、请求、预置、metrics 与引擎日志，输出到新的独立目录；不联网、不启动服务，也不清理运行中的缓存。
- [离线审计测试](scripts/test_audit_sla_cache.py)：使用临时合成证据，覆盖 HTTP 200 但没有本轮成功日志、预置残留缓存、正式请求超额命中、数据损坏等情形。
- [修正后的标准 SLA 入口](scripts/standard_sla.py)：2026-09-14 V4 Flash 对照使用原生 SGLang 客户端/指标和默认指数到达；支持原精确 token 数据与用户 GSP 文本，逐帧同时记录首 token 和首非空文本时间。默认仅离线检查，`--execute` 才清理本地空闲 worker 缓存并测试；不管理引擎生命周期。此机器上的权重/运行时/证据默认路径不是通用安装配置。
- [标准计时一致性测试](scripts/test_standard_sla.py)：同一组模拟 SSE 喂给未修改的原生客户端与增加观测的客户端，校验结果逐字段相同，覆盖空首 token、投机多 token 帧和协议尾部。历史快照仍保持原字节，不作为新的 SLA 默认入口。
- [客户端 shell 入口](scripts/bench_v4_flash_sla_corrected.sh) 与 [V4 Flash TP2 服务端入口](scripts/start_v4_flash_0731_tp2.sh)：使用机器快照中的固定 runtime/模型/数据路径；客户端从自身目录定位 `standard_sla.py`，不依赖仓库克隆位置。客户端默认离线检查；服务端默认会启动模型，审阅只传 `--dry-run`。依赖、命令与日志注意事项见[交接说明](references/code-review-20260914.md#修正后-v4-flash-复现入口)。

## 执行顺序

1. 把模型版本、实际卡数、两种部署策略、输入/输出长度、缓存口径、正式样本数、SLA 判据和计价情景写入计划。既有确认不反复询问；有冲突时优先遵循最新用户指令。
2. 从各自官网取得命中输入、未命中输入、输出价格，保留 URL、查询日期、币种、单位、区域与有效条件。区分在售模型和同名 API 别名实际路由的版本。
3. 搜索本地已有权重，先做具备权重的模型。核对 tokenizer、权重索引及运行环境；没有权限或缺权重时记录缺口，不自行下载 TB 级权重或增租资源。
4. 在已授权资源内逐模型部署。分别记录 High-Throughput 和 Low-Latency 的完整命令、镜像 digest/源码 commit、有效参数及 GPU 拓扑。启动成功不等于性能通过。
5. 先测 `request_rate=inf`、无客户端并发上限的统一吞吐档；随后用对应低延迟配置搜索各模型 SLA 下的最高通过速率点。两种配置结果分列。
6. 每完成一个点就保留逐请求证据；每完成一个模型立即更新 Markdown。报告实际完成的输入/命中/未命中/输出 TPM、延迟、成功率、边界及实际占用卡数下的月收入。

## 不可混淆的边界

- 无客户端 concurrency cap 不等于删除服务端安全上限；记录引擎实际的 running/queue/KV 限制。
- 共享前缀构造比例、请求复用比例、实际输入 token 缓存命中率是三个不同量。
- 发压目标 RPS 不等于完成 RPS；SSE chunk 数不等于输出 token 数，尤其启用投机解码时。
- 固定批次的最高通过点不是无限时间稳态容量；按不同 SLA 和各自优化配置比较，不得解释为纯模型效率排序。
- 降低卡数是待实测的部署选择，不是“权重文件能装下就一定可用”。缺失质量评测不能由吞吐成功代替。
- 只停止已核对 PID、启动时间、任务标记/进程组的本任务实例。不要修改线上服务、停止无关进程，或使用广泛的 `pkill`。
- OOM、重启、缓存目标失效、发压器瓶颈或中断都保留原记录；基础设施异常先诊断，不自动扩大资源、改 SLA 或无限重试。

本 skill 的快照包含历史压测队列和生命周期入口；仅阅读、校验或发布 skill 不会自动运行它们。真正恢复执行前，核对实例所有权、路径/环境、最新配置和样本规则；历史 active-engine/approval 文件不能当作当前有效状态。
