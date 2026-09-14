# 六模型 SLA 缓存隔离与计量审计

这是历史证据的离线核对，不是新的性能测试。审计 PASS 与原点 SLA PASS 是不同判据。

共 43 个 SLA 尝试点；审计状态：`{'PASS': 40, 'INCOMPLETE': 2, 'FAIL': 1}`。

## 用户表中的六个点

| 模型 | 审计 | flush 日志条数 | 首次预置 cached tokens | 超出公共前缀的请求 | 实际命中率 | 重算总 TPM |
|---|---|---:|---|---:|---:|---:|
| GLM 5.3 FP8 | PASS | 1 | [0] | 0 | 94.443147% | 3,692,844 |
| GLM 5.3 Flash FP8 | PASS | 1 | [0] | 0 | 92.541478% | 6,549,115 |
| V4.1 Flash | PASS | 1 | [0] | 0 | 93.200000% | 38,931 |
| V4 Flash 0731 | PASS | 1 | [0] | 0 | 79.598837% | 3,223,783 |
| V4 Pro 0813 | PASS | 1 | [0] | 0 | 86.613402% | 2,249,744 |
| GLM 5.3 NVFP4 | PASS | 1 | [0] | 0 | 94.440709% | 3,088,407 |

## 每轮证据

| 点 | 原 SLA 状态 | 保存请求 / 成功 | 审计 | 问题或缺失证据 |
|---|---|---:|---|---|
| glm53-resume-07-sla-p01-r0.250000 | PASS | 200 / 200 | PASS | 无 |
| glm53-resume-07-sla-p02-r0.500000 | PASS | 200 / 200 | PASS | 无 |
| glm53-resume-07-sla-p03-r1.000000 | FAIL | 200 / 200 | PASS | 无 |
| glm53-resume-07-sla-p04-r0.750000 | PASS | 200 / 200 | PASS | 无 |
| glm53-resume-07-sla-p05-r0.875000 | PASS | 200 / 200 | PASS | 无 |
| glm53-resume-07-sla-p06-r0.937500 | FAIL | 200 / 200 | PASS | 无 |
| glm53flash-resume-07-sla-p01-r0.250000 | 未完成 | 5 / 5 | INCOMPLETE | no_final_summary |
| glm53flash-resume-08-sla-p01-r0.250000 | PASS | 200 / 200 | PASS | 无 |
| glm53flash-resume-08-sla-p02-r0.500000 | PASS | 200 / 200 | PASS | 无 |
| glm53flash-resume-08-sla-p03-r1.000000 | PASS | 200 / 200 | PASS | 无 |
| glm53flash-resume-08-sla-p04-r2.000000 | FAIL | 200 / 200 | PASS | 无 |
| glm53flash-resume-08-sla-p05-r1.500000 | PASS | 200 / 200 | PASS | 无 |
| glm53flash-resume-08-sla-p06-r1.750000 | FAIL | 200 / 200 | PASS | 无 |
| glm53flash-resume-08-sla-p07-r1.625000 | PASS | 200 / 200 | PASS | 无 |
| v41-resume-02-sla-p01-r0.250000 | FAIL | 200 / 200 | PASS | 无 |
| v41-resume-02-sla-p02-r0.125000 | FAIL | 200 / 200 | PASS | 无 |
| v41-resume-02-sla-p03-r0.062500 | PASS | 200 / 200 | PASS | 无 |
| v41-resume-02-sla-p04-r0.093750 | FAIL | 200 / 200 | PASS | 无 |
| v41-resume-02-sla-p05-r0.078125 | FAIL | 200 / 200 | PASS | 无 |
| v41-resume-02-sla-p06-r0.070312 | PASS | 200 / 200 | PASS | 无 |
| v41-resume-02-sla-p07-r0.074219 | FAIL | 200 / 200 | PASS | 无 |
| v4flash-resume-02-sla-p01-r0.250000 | PASS | 200 / 200 | PASS | 无 |
| v4flash-resume-02-sla-p02-r0.500000 | PASS | 200 / 200 | PASS | 无 |
| v4flash-resume-02-sla-p03-r1.000000 | PASS | 200 / 200 | PASS | 无 |
| v4flash-resume-02-sla-p04-r2.000000 | PASS | 200 / 200 | PASS | 无 |
| v4flash-resume-02-sla-p05-r4.000000 | FAIL | 200 / 200 | PASS | 无 |
| v4flash-resume-02-sla-p06-r3.000000 | FAIL | 200 / 200 | PASS | 无 |
| v4flash-resume-02-sla-p07-r2.500000 | PASS | 200 / 200 | PASS | 无 |
| v4flash-resume-02-sla-p08-r2.750000 | FAIL | 200 / 200 | PASS | 无 |
| v4pro-resume-11-sla-p01-r0.250000 | 未完成 | 0 / 0 | FAIL | preseed_length_mismatch, preseed_request_failed, no_final_summary, preseed_cache_count_missing |
| v4pro-resume-12-sla-p01-r0.250000 | PASS | 200 / 200 | PASS | 无 |
| v4pro-resume-12-sla-p02-r0.500000 | PASS | 200 / 200 | PASS | 无 |
| v4pro-resume-12-sla-p03-r1.000000 | FAIL | 200 / 200 | PASS | 无 |
| v4pro-resume-13-sla-p04-r0.750000 | PASS | 200 / 200 | PASS | 无 |
| v4pro-resume-13-sla-p05-r0.875000 | FAIL | 200 / 200 | PASS | 无 |
| v4pro-resume-13-sla-p06-r0.812500 | FAIL | 200 / 200 | PASS | 无 |
| sla-tp8-mtp5-mem085-01-p01-r0.250000 | 未完成 | 4 / 4 | INCOMPLETE | no_final_summary |
| sla-tp8-mtp5-mem085-02-p01-r0.250000 | PASS | 200 / 200 | PASS | 无 |
| sla-tp8-mtp5-mem085-02-p02-r0.500000 | PASS | 104 / 104 | PASS | 无 |
| sla-tp8-mtp5-mem085-02-p03-r1.000000 | FAIL | 200 / 200 | PASS | 无 |
| sla-tp8-mtp5-mem085-02-p04-r0.750000 | PASS | 119 / 119 | PASS | 无 |
| sla-tp8-mtp5-mem085-02-p05-r0.875000 | FAIL | 200 / 200 | PASS | 无 |
| sla-tp8-mtp5-mem085-02-p06-r0.812500 | FAIL | 200 / 200 | PASS | 无 |

## 边界

- HTTP 200 不是独立的清理成功证据；同时核对当前轮时间窗内的 scheduler 日志、预置命中计数和正式请求缓存上界。
- 首次预置无缓存且正式命中不超出公共前缀，支持没有利用上一轮完整 prompt 缓存；不证明真实业务具有相同工作集或性能。
- 共享前缀在计时前预置；预置成本不计入正式窗口。总 TPM 包含命中输入，不等于新增 prefill 或输出 TPM。
- 源码哈希、数据哈希、逐点指标差值及日志行号见 `audit.json`。未完成点不用于填补或拼接正式结果。
- 离线证据无法验证未被采集的事件；缺失记录标 INCOMPLETE，不能当作成功或直接认定漏 flush。
