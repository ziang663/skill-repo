# H200 部署方案快照

以下是 2026-09-13 已整理的 SGLang cookbook 配置。执行前重新查对应版本、H200、策略的精确配置 cell；变化先说明，不静默替换已确认的模型版本或卡数。

## 来源与选择原则

- [DeepSeek V4.1](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4_1)
- [DeepSeek V4](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4)
- [GLM 5.3](https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3)
- [GLM 5.3 Flash](https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3-Flash)

若页面交互配置未出现在正文，检查其 `.md` 版本及 `cells`；不要从 B200、GB300 或泛化段落补出 H200 没有的参数。保留读取日期、原始页面、cell 选择器、验证标记及内容哈希。

全部为单机 PP1，无外部 router，无 P/D 分离。TP8/DP8 attention 是8卡内的并行分工，**不是8套完整 TP8 模型副本**。未显式指定的参数保留对应引擎默认并记录实际值，不能凭表格空白推测值。

| 模型 | H200 | 高吞吐 | SLA 低延迟 |
|---|---:|---|---|
| V4.1 Flash | 8 | TP8/EP8、DP1，mem .8，dsv4、flashinfer_mxfp4，decode graph max BS64，max-running256，无投机 | TP8/EP8、DP1，mem .8，同后端及 graph，decoder SWA bounded replay，无投机 |
| V4 Flash 0731 | **2** | TP2、DP1，marlin，无投机 | TP2、DP1，flashinfer_mxfp4、precision fp8，DSPARK |
| V4 Pro 0813 | 8 | TP8、DP1，flashinfer_mxfp4，mem .88，无投机 | TP8、DP1，flashinfer_mxfp4，mem .90，DSPARK |
| GLM 5.3 FP8 | 8 | TP8/DP8 attention，DeepEP，EAGLE 1/1/2，mem .85，chunk32768，max-running256 | TP8/DP1，无 DP attention，EAGLE 5/1/6，mem .8 |
| GLM 5.3 Flash FP8 | **4** | TP4/EP4、DP1，DSA prefill/decode tilelang，BF16 KV，deep_gemm，无投机 | 同并行/后端，EAGLE 5/1/6，mem .75 |

EAGLE 三元组依次为 num-steps / eagle-topk / num-draft-tokens。V4 Flash 从 cookbook 4卡改为2卡、GLM 5.3 Flash 从8卡改为4卡，是用户明确选择；不能宣称这些缩卡配置已经官方验证。若不能加载或在所需上下文工作，保留证据并请求方向，不擅自增加卡数。

### V4.1 Flash

两种策略共有参数：

```text
--trust-remote-code --tp 8 --ep-size 8 --mem-fraction-static 0.8
--attention-backend dsv4 --moe-runner-backend flashinfer_mxfp4
--cuda-graph-max-bs-decode 64 --reasoning-parser auto --tool-call-parser auto
```

高吞吐增加 `--max-running-requests 256`；低延迟增加 `--enable-decoder-swa-bounded-replay`。H200 低延迟 cell **没有 DSPARK**。精确 cell 指定后端，与页面泛化的“不 override backend”说明不完全一致，采用精确 cell 并记录差异。

### V4 Flash 0731

共有 `--trust-remote-code --tp 2`。

- 高吞吐：`--moe-runner-backend marlin`。
- 低延迟：`--moe-runner-backend flashinfer_mxfp4 --flashinfer-mxfp4-moe-precision fp8 --speculative-algorithm DSPARK`。

### V4 Pro 0813

共有 `--trust-remote-code --tp 8 --moe-runner-backend flashinfer_mxfp4`。

- 高吞吐：`--mem-fraction-static 0.88`。
- 低延迟：`--mem-fraction-static 0.90 --speculative-algorithm DSPARK`。

### GLM 5.3 FP8

共有 `--tp 8`。高吞吐增加：

```text
--dp 8 --enable-dp-attention --moe-a2a-backend deepep
--speculative-algorithm EAGLE --speculative-num-steps 1
--speculative-eagle-topk 1 --speculative-num-draft-tokens 2
--mem-fraction-static 0.85 --chunked-prefill-size 32768 --max-running-requests 256
```

低延迟增加：

```text
--speculative-algorithm EAGLE --speculative-num-steps 5
--speculative-eagle-topk 1 --speculative-num-draft-tokens 6
--mem-fraction-static 0.8
```

### GLM 5.3 Flash FP8

共有参数：

```text
--tp-size 4 --ep-size 4 --dsa-prefill-backend tilelang --dsa-decode-backend tilelang
--kv-cache-dtype bfloat16 --moe-runner-backend deep_gemm
--reasoning-parser glm45 --tool-call-parser glm47
```

高吞吐不另加投机；低延迟增加：

```text
--mem-fraction-static 0.75 --speculative-algorithm EAGLE
--speculative-num-steps 5 --speculative-eagle-topk 1 --speculative-num-draft-tokens 6
```

## 镜像及验证边界

当日 cookbook 镜像：V4.1 为 `lmsysorg/sglang:dev-dsv41`；V4 Flash、V4 Pro、GLM 5.3 为 `lmsysorg/sglang:latest`；GLM 5.3 Flash 为 `lmsysorg/sglang:glm-5.3-flash`。这些都是可变 tag，必须在执行记录中固定 digest 和引擎版本；不同模型不得随意混用依赖环境。

当日验证标记：V4.1 两档及 GLM 5.3 两档为 verified；V4 Flash 0731 低延迟为 in-progress、高吞吐为 verified；V4 Pro 0813 两档 `verified=false`；GLM 5.3 Flash 低延迟动态状态为 in-progress、高吞吐为 verified。标记不是本轮通过结果，且不覆盖用户缩卡方案。

这组参数片段不是可直接启动的完整命令。执行时补上已核对的权重路径、served-model-name、本地绑定地址/端口、GPU 可见列表、指标与缓存计量参数，并核对 CLI 支持情况。只提取镜像内 Python/源码而沿用宿主 CUDA/OS 时，明确这是部分环境复用，不称完整同容器运行。

启动前核对权重变体、量化、索引 shard、tokenizer、MTP/投机所需权重与内核依赖；记录 TP/EP/DP、DP attention、KV dtype/page/pool、context、chunked prefill、max running、CUDA graph、投机实际参数、thinking 设置和 GPU 峰值内存。上下文输入+输出必须可容纳，KV 公式不能替代临时张量/运行时内存验证。
