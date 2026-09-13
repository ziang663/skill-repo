# 官网定价与收入核算

## 采价方法

核对官网的**模型实际版本**、地区/计费平台、币种、每百万 token 单位、有效日期。分别记录 cached input、uncached input、output；不要把缓存写入、存储、读取费混为一项。注明推理 token 是否包含在 output、是否有长上下文阶梯价、峰谷时段、限时优惠和工具附加费。

官网查不到或只有历史价时标明“未取得现价 / 历史情景”，不使用其他模型或第三方聚合价冒充。混用币种前需注明汇率来源与日期。

## 2026-09-13 价格快照

下表来自本轮已保存的官网资料，单位为 **USD / 1,000,000 tokens**，列顺序为命中输入 / 未命中输入 / 输出。复用时重新核对，不将此快照永远视为现价。

| 模型 | 峰价或全天价 | 谷价 | 来源及性质 |
|---|---|---|---|
| DeepSeek V4.1 Flash | 0.006 / 0.30 / 1.20 | 0.003 / 0.15 / 0.60 | [DeepSeek 价格页](https://api-docs.deepseek.com/quick_start/pricing)，当日在售价 |
| DeepSeek V4 Flash 0731 | 0.014 / 0.44 / 1.32 | 0.007 / 0.22 / 0.66 | [2026-08-13 公告](https://api-docs.deepseek.com/news/news260813)、[价格图](https://api-docs.deepseek.com/img/v4_260813_price_en.png)，**历史情景** |
| DeepSeek V4 Pro 0813 | 0.044 / 1.32 / 3.96 | 0.022 / 0.66 / 1.98 | [DeepSeek 价格页](https://api-docs.deepseek.com/quick_start/pricing)，当日在售价 |
| GLM 5.3 | 0.26 / 1.40 / 4.40 | — | [Z.ai 国际定价](https://docs.z.ai/guides/overview/pricing)，全天 |
| GLM 5.3 Flash | 0.03 / 0.15 / 0.50 | — | [Z.ai 国际定价](https://docs.z.ai/guides/overview/pricing)，全天 |

- DeepSeek [变更记录](https://api-docs.deepseek.com/updates)：旧 V4 Flash 于 2026-09-10 退役；旧 API 别名转到 V4.1。旧权重可以本地评测，但不能套用同名现行 API 的 V4.1 价格冒充旧版现价。
- 当日现行 DeepSeek 峰时是周一至周五 UTC 01:00–04:00、06:00–10:00，其余半价。历史 V4 Flash 公告仅列每日这些时段，历史情景单独处理；价格自 2026-08-16 16:00 UTC 生效。
- 当日 Z.ai 缓存存储为限时免费，不表示永久免费；本轮使用国际 USD API 价格，不混入国内平台价或订阅套餐额度。

## 计算

只使用有效正式测量窗口 `T` 内**成功请求实际计量**的 tokens：

```text
cached_tps   = sum(cached_input_tokens) / T_seconds
uncached_tps = sum(input_tokens - cached_input_tokens) / T_seconds
output_tps   = sum(output_tokens) / T_seconds
input_TPM    = (cached_tps + uncached_tps) * 60
output_TPM   = output_tps * 60
total_TPM    = input_TPM + output_TPM

monthly_revenue_per_GPU =
  (cached_tps * price_cached_per_M
   + uncached_tps * price_uncached_per_M
   + output_tps * price_output_per_M)
  * 2_592_000 / 1_000_000 / actual_GPU_count
```

失败请求及其部分生成 token 单列，不伪装为完整成功请求收入。失败点可以描述有效完成吞吐，但不能作为可靠满载营收工作点。测量结果没有可信缓存计量时，只能列明确标注的目标命中率收入情景，不能写成实测命中收入。

存在分时计价时，按同一满载 token 速率分别乘各时段秒数及其价格后相加，而不是将峰价乘整月。必须明确 UTC 起止时间和时段是否在周末适用；若不选择日期窗口，则分别给全峰/全谷情景并标明其假设。

本轮可用窗口是 `[2026-09-13 00:00, 2026-10-13 00:00) UTC`：现行 DeepSeek 为147峰时小时+573谷时小时；V4 Flash 历史“每日峰时”情景为210+510小时。这些小时数只属于这个30天情景，不能固化成通用月份权重。

预置缓存、预热、故障恢复、维护和真实需求不足均可能减少生产收益。30天满载是用户要求的理论外推；本轮不扣未提供的硬件租赁/采购、电力或运维成本，不称利润。
