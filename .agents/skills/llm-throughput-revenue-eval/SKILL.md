---
name: llm-throughput-revenue-eval
description: Plan and evaluate local SGLang LLM throughput, SLA-constrained TPM, and per-GPU monthly revenue using official cached-input, uncached-input, and output prices. Use for model-serving capacity and token-economics studies, including the five-model H200 plan; not for unrelated API compatibility acceptance or production service changes.
---

# LLM 吞吐、SLA 与单卡收入核算

把官网计价、可复现的本地部署、实际完成的 token 吞吐和业务延迟约束连接起来。没有硬件、电力等成本输入时，只给理论营业收入，不能称为利润或净收益。

## 先确定工作模式

- **整理计划 / 审阅结果**：只整理需求、核对来源和证据，不启动部署或发压。
- **执行实验**：需要用户已经授权本地部署与测试；先确认资源占用、准确模型版本和运行预算，再开始。
- **暂停 / 续跑**：暂停时先停本任务队列及发压，再安全停止本任务引擎并保留证据。用户说“先暂停”后，阅读或发布此 skill 不代表获准恢复。

本轮五模型任务在 2026-09-13 被用户暂停；后续恢复须有新的执行指令。复用到其他任务时，不把该历史状态当作新任务的状态。

## 需要读取的资料

- 复现本轮五模型任务或核对其要求：读取 [五模型目标与 SLA](references/five-model-h200-plan.md)。以用户最新确认覆盖早期草稿，不能带回已取消的 P95 条件或旧样本数。
- 核对/启动 H200 配置：读取 [部署方案快照](references/h200-deployment-profiles.md)，重新检查对应模型、权重变体、芯片及策略的官方 cookbook cell。
- 采集价格或核算收入：读取 [定价与收入](references/pricing-and-revenue.md)。其中的价格是有日期的快照，不能无条件作为现价。
- 构建数据、发压、判定 SLA 或解释结果：读取 [测量口径](references/measurement-method.md)。
- 创建/更新 Markdown 报告：采用 [报告模板](assets/report-template.md)，按实际进展填写，未测处保留“未测”。

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

本 skill 保存计划与判定方法，不附带自动启动的压测队列。恢复已有执行器前，核对其实际参数是否与最新计划一致。
