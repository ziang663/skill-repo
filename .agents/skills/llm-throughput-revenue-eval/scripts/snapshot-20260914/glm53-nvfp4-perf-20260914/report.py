"""Generate a separate report after every completed NVFP4 point."""
import json
from pathlib import Path
from experiment import ROOT, lifecycle


def number(value, places=0):
    return '—' if value is None else f'{value:,.{places}f}'


def revenue(s):
    if any(s.get(k) is None for k in ('cached_input_tpm','uncached_input_tpm','output_tpm')):
        return None
    return (s['cached_input_tpm']*.26+s['uncached_input_tpm']*1.4+s['output_tpm']*4.4)*43200/1e6/s['gpus']


def main():
    summaries = [(path.parent.name, json.loads(path.read_text()))
                 for path in sorted((ROOT/'benchmarks').glob('*/summary.json'))]
    pause_path = ROOT/'sla-review.json'
    pause = json.loads(pause_path.read_text()) if pause_path.exists() else None
    policy_path = ROOT/'warning-policy-20260914.json'
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
    reassess_path = ROOT/'throughput-reassessment-20260914.json'
    reassess = json.loads(reassess_path.read_text()) if reassess_path.exists() else None
    lines = ['# GLM 5.3 NVFP4：吞吐、SLA 与单卡理论收入', '',
             f'更新：{lifecycle.utc()}。只汇总本目录实测，原五模型结果保持不变。', '',
             '## 官网价格', '',
             '| 模型 | 未命中输入 USD/M | 命中输入 USD/M | 输出 USD/M |',
             '|---|---:|---:|---:|', '| GLM 5.3 | 1.40 | 0.26 | 4.40 |', '',
             '来源：[Z.ai 官网定价快照](../glm53-nvfp4-kv-20260914/sources/zai-pricing-20260914.md)，2026-09-14 核对；缓存存储限时免费。NVFP4 按 GLM 5.3 API 售价作理论情景，不代表量化精度与官网服务等价。', '',
             '## 配置及口径', '',
             '见 [测试计划](PLAN.md) 和 [部署参数](profiles.json)。8×H200、mem=0.85、NVFP4+Marlin、FP8 KV、关闭共享专家融合；吞吐 DPA，SLA MTP。实际参数以各 run 的 launch.json/server-info.json 为准。', '',
             '统一吞吐：76,800 输入 / 1,024 输出、缓存目标90%、inf、客户端无并发上限、200条。SLA：72,125 / 1,095、缓存目标94.532%；平均TTFT≤1.397秒且平均TPOT≤16.666667ms。缓存容差±0.5个百分点。最新规则允许前100条全部完成且达标时停止发送新请求并排空在途；未达标则继续到200条，实际样本数逐点列明。已在运行的0.25 RPS基线仍完成200条。', '',
             '## 统一 inf 吞吐', '',
             '| 点 | 成功/计划 | 输入TPM | 命中TPM | 未命中TPM | 输出TPM | 总TPM | 缓存率 | 单卡30天收入USD | 判定 |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
    audit_path=ROOT/'final-audit.json'
    if audit_path.exists():
        audit=json.loads(audit_path.read_text())
        best=audit['best']
        release_path=ROOT/'runs'/audit['engine_run']/'released.json'
        released=release_path.exists() and json.loads(release_path.read_text()).get('gpus_released')
        conclusion=['## 完成结论', '',
                    f"SLA搜索已完成并逐请求复核：{audit['point_count']}个点、{audit['completed_formal_requests']:,}条正式请求全部成功，无crash/重启；{audit['passing_points']}点通过，{audit['failed_latency_points']}点仅TPOT超限。allocator告警按用户口径保留但不判失败。", '',
                    f"最高已测通过点：目标{best['target_rps']} RPS、实际完成{best['completed_rps']:.6f} RPS、{best['requests']}/{best['requests']}成功，mean TTFT={best['ttft_s']:.6f} s、mean TPOT={best['tpot_ms']:.6f} ms，总TPM={best['total_tpm']:,.0f}，单卡30天理论收入=${best['monthly_revenue_per_gpu_usd']:,.2f}。相邻失败目标RPS={audit['target_rps_bracket'][1]}；有限样本边界，不是全局稳态容量证明。", '',
                    '统一吞吐与SLA的输入/输出长度、缓存目标及并行/MTP配置不同，结果分别使用；总TPM含缓存输入，不等于实际计算的prefill吞吐。', '',
                    f"资源状态：{'本地测试实例已停止，8卡及端口已释放' if released else '停止/释放确认待检查'}。摘要见 [最终结果](FINAL-RESULTS.md)，复核见 [final-audit.json](final-audit.json)。", '']
        lines[4:4]=conclusion
    through = [(name,s) for name,s in summaries if s['scenario']=='throughput']
    for name,s in through:
        value = revenue(s)
        accepted = reassess and reassess['point']==name and reassess['status']=='PASS_WITH_WARNING'
        money = f'{value:,.2f}' if value is not None and (s['status']=='PASS' or accepted) else '不作为有效收入点'
        status = '新口径通过（1条告警；原始FAIL保留）' if accepted else s['status']+' '+ '/'.join(s['failure_reasons'])
        hit=number(s['observed_cache_rate']*100,4)+'%' if s['observed_cache_rate'] is not None else '未知'
        lines.append(f"| [{name}](benchmarks/{name}/summary.json) | {s['success']}/{s['requests']} | {number(s['input_tpm'])} | {number(s['cached_input_tpm'])} | {number(s['uncached_input_tpm'])} | {number(s['output_tpm'])} | {number(s['total_tpm'])} | {hit} | {money} | {status} |")
    if not through:
        lines.append('| 未测 | — | — | — | — | — | — | — | — | 未测 |')
    if policy:
        lines += ['', '最新用户口径：allocator OOM告警只记录，不单独判失败；仍要求无crash/重启、已发送请求全部成功、缓存计量有效，SLA仍需平均TTFT/TPOT达标。见 [告警口径](warning-policy-20260914.json) 和 [100条提前结束规则](adaptive-sampling-policy-20260914.json)。吞吐原始FAIL不改写，按新口径复核为通过（有告警），见 [独立复核](throughput-reassessment-20260914.json)。']
    for name,s in through:
        lines += ['', f"{name}：正式窗口 {s['duration_s']:.2f} 秒，完成 {s['completed_rps']:.6f} RPS；mean TTFT={number(s['ttft_s']['mean'] if s['ttft_s'] else None,4)} s，mean TPOT={number(s['tpot_ms']['mean'] if s['tpot_ms'] else None,4)} ms。预置耗时 {s['preseed_duration_s']:.2f} 秒，不计正式窗口。"]
    lines += ['', '## SLA 搜索', '',
              '| 点 / 目标RPS | 完成RPS | 成功/实发（最大计划200） | Mean TTFT s | Mean TPOT ms | 输入TPM | 输出TPM | 总TPM | 缓存率 | 单卡30天收入USD | 判定 |',
              '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|']
    sla = [(name,s) for name,s in summaries if s['scenario']=='sla']
    for name,s in sla:
        value = revenue(s)
        money = f'{value:,.2f}' if value is not None and s['status']=='PASS' else '不作为达标收入点'
        ttft = f"{s['ttft_s']['mean']:.4f}" if s['ttft_s'] else '—'
        tpot = f"{s['tpot_ms']['mean']:.4f}" if s['tpot_ms'] else '—'
        hit=number(s['observed_cache_rate']*100,4)+'%' if s['observed_cache_rate'] is not None else '未知'
        warning_note = f"；本点告警{s.get('allocator_warning_count_this_point', 0)}条"
        if s.get('adaptive_sampling', {}).get('early_stopped'):
            warning_note += '；100条检查后提前收尾'
        lines.append(f"| [{s['request_rate']}](benchmarks/{name}/summary.json) | {s['completed_rps']:.6f} | {s['success']}/{s['requests']} | {ttft} | {tpot} | {s['input_tpm']:,.0f} | {s['output_tpm']:,.0f} | {s['total_tpm']:,.0f} | {hit} | {money} | {s['status']} {'/'.join(s['failure_reasons'])}{warning_note} |")
    if pause:
        lines.append(f"| [{pause['target_rps']}（旧批次中断）](benchmarks/{pause['point']}/interruption.json) | — | 已保存成功{pause['persisted_successes']}/{pause['planned_requests']}；非完整批次 | — | — | — | — | — | — | 不计算 | 历史中断，不计入新批次 |")
    elif not sla:
        lines.append('| 未测 | — | — | — | — | — | — | — | — | — | 未测 |')
    searches = sorted(ROOT.glob('*-search.json'))
    if (ROOT/'adaptive-sampling-policy-20260914.json').exists():
        lines += ['', '搜索控制器启动时的requests_per_point=200及“200-request”说明是原计划上限；运行中用户批准100条达标提前结束，逐点实际样本数以summary.json为准。前100条不达标时继续200条；已发出的在途请求全部计入最终均值/TPM，排空后若不达标仍判FAIL。']
    for path in searches:
        state = json.loads(path.read_text())
        displayed = pause['status'] if pause and state.get('engine_run') == pause['active_engine']['name'] else state['status']
        lines += ['', f"搜索状态：`{displayed}`；搜索记录见 [{path.name}]({path.name})。"]
        if displayed != state['status']:
            lines += ['', '旧批次人工SIGINT中断时，内层搜索记录停留在running；外层控制器已needs_review，以 [历史SLA中断复核](SLA-REVIEW.md) 为准。该旧批次没有完整200条点，不与新批次拼接。']
        best = state.get('best_measured_pass')
        if best:
            lines += ['', f"最高实测通过 TPM：{best['total_tpm']:,.0f}，目标 RPS={best['rate']}；不宣称全局最大稳态容量。"]
    lines += ['', '## 实际部署信息', '',
              '| Run | TP / DP / EP | DPA | mem | KV dtype | 单调度单元 KV pool | 最大输入 | MTP steps/topk/draft |',
              '|---|---|---|---:|---|---:|---:|---|']
    for path in sorted((ROOT/'runs').glob('*/launch.json')):
        run=path.parent
        info_path=run/'server-info.json'
        if not info_path.exists():
            lines.append(f'| [{run.name}](runs/{run.name}/launch.json) | 有效参数待采集 | — | — | — | 未取得 | 未取得 | — |')
            continue
        info=json.loads(info_path.read_text())
        base=info.get('server_args',info)
        resolved={**base, **(info.get('internal_states') or [{}])[0]}
        mtp='/'.join(str(resolved.get(k)) for k in ['speculative_num_steps','speculative_eagle_topk','speculative_num_draft_tokens']) if resolved.get('speculative_algorithm') else '关闭'
        lines.append(f"| [{run.name}](runs/{run.name}/server-info.json) | {resolved.get('tp_size')}/{resolved.get('dp_size')}/{resolved.get('ep_size')} | {resolved.get('enable_dp_attention')} | {resolved.get('mem_fraction_static')} | {resolved.get('kv_cache_dtype')} | {number(resolved.get('max_total_num_tokens',info.get('max_total_num_tokens')))} | {number(resolved.get('max_req_input_len',info.get('max_req_input_len')))} | {mtp} |")
    lines += ['', 'KV pool 取单调度单元的有效值，不把 TP rank 相加；DPA 各单元值和内存详情保留在原始 server-info。模型声明1M不是容量或稳定性证明。']
    if pause:
        lines += ['', '## 历史 SLA 预置告警与中断', '',
                  f"单调度单元实际KV pool={pause['single_scheduler_kv_pool']:,} tokens，超过1,048,576；最大输入={pause['max_req_input_len']:,}。这是容量配置证据，不是1M请求稳定性通过。", '',
                  f"旧run的68,224-token缓存预置过程中，全8个rank各出现1条约2.01 GiB分配OOM告警，共{pause['oom_warning_count']}条；预置仍成功，人工停机前health=200、无引擎崩溃。该run首个0.25 RPS点仅保存{pause['persisted_successes']}条成功结果后人工中断，不计算SLA TPM或收入；旧进程已停止释放。详见 [历史SLA复核](SLA-REVIEW.md)。"]
    review_path=ROOT/'throughput-review.json'
    if review_path.exists():
        review=json.loads(review_path.read_text())
        continuation='SLA尚未执行，按用户要求先讨论。'
        approval_path=ROOT/'sla-continuation-approval.json'
        if policy:
            approval_path=policy_path
        if approval_path.exists():
            approval=json.loads(approval_path.read_text())
            controller_path=ROOT/(approval['run_name']+'-controller.json')
            controller=json.loads(controller_path.read_text()) if controller_path.exists() else {}
            state=controller.get('status', 'approved_pending_start')
            continuation=f"用户已批准独立继续SLA，新run `{approval['run_name']}` 控制器状态：`{state}`；逐点结果和搜索边界见上文。allocator告警仅记录，其他异常仍检查；部署参数未变。"
        lines += ['', '## 吞吐告警与 SLA 继续状态', '',
                  '吞吐200/200完成，出现1条rank3的3 GiB显存分配OOM告警；服务未退出，测试后健康检查通过。原始FAIL代表日志稳定性检查不通过，不代表请求失败。'+continuation, '',
                  f"按本批实际完成tokens折算的单卡30天收入情景为 **${review['monthly_per_gpu_observed_scenario_usd']:,.2f}**；这是有告警样本的理论外推，不是稳定性准出或可靠生产收入承诺。完整说明见 [告警复核](THROUGHPUT-REVIEW.md)。"]
    lines += ['', '## 计量与限制', '',
              'TPM 按成功请求实际输入/缓存/输出 token 总量除以正式窗口计算，包含填充和排空；单卡收入按实际8卡、30天满载外推。不使用目标RPS冒充完成RPS。无成本输入，不称利润。', '',
              '原生 loopback /generate + input_ids；不含 router/Chat 模板。固定随机 token、ignore_eos、temperature=0；MTP接受率使用实测，没有模拟接受率。预热和各DPA单元前缀预置单独记录，不计正式窗口。', '',
              'FP8 KV 默认 scaling factors=1.0 的启动警告及前次失败保留；本轮不验证精度、工具质量、1M请求稳定性或真实流量。SLA档与吞吐档的负载、缓存目标及部署不同，不能把二者差值全部归因为某个优化。', '',
              '原始证据在 benchmarks/ 和 runs/；未完成或中断点不纳入成功汇总。按评测 skill 独立留档，未覆盖历史失败。', '']
    (ROOT/'RESULTS.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
