"""Build a compact evidence-backed overview without changing raw results."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from report_results import PROFILES, PRICES, revenue, number

ROOT = Path(__file__).resolve().parent


def read(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def formal_results():
    results = []
    for path in sorted((ROOT / 'benchmarks').glob('*/summary.json')):
        item = read(path)
        if item.get('requests') == 200:
            item['evidence'] = str(path.relative_to(ROOT))
            results.append(item)
    return results


def chosen(results, model, scenario):
    valid = [s for s in results if s['model'] == model and s['scenario'] == scenario
             and s['status'] == 'PASS' and s['success'] == 200]
    return max(valid, key=lambda s: s['total_tpm']) if valid else None


def user_accepted_throughput(results):
    """Explicit reporting exception; never alter original PASS/FAIL selection."""
    review = read(ROOT / 'v4pro-throughput-user-acceptance.json')
    if not review:
        return None
    assert review['authority'] == 'explicit_user_request'
    assert (review['model'], review['scenario']) == ('v4pro', 'throughput')
    primary = review['primary_point']
    evidence = f'benchmarks/{primary}/summary.json'
    item = next(s for s in results if s['evidence'] == evidence)
    entry = next(p for p in review['accepted_points'] if p['name'] == primary)
    assert hashlib.sha256((ROOT / evidence).read_bytes()).hexdigest() == entry['summary_sha256']
    assert (item['model'], item['scenario'], item['request_rate']) == ('v4pro', 'throughput', 'inf')
    assert item['engine_run'] == review['engine_run'] and item['gpus'] == 8
    assert item['requests'] == item['success'] == 200
    assert item['status'] == 'FAIL' and item['failure_reasons'] == ['cache_rate_mismatch']
    assert item['observed_cache_rate'] == review['observed_cache_rate']
    assert all(v['http'] == 200 for v in item['health_after'].values())
    return item


def money(item):
    value = revenue(item)
    if value is None:
        return '未取得可信缓存计量'
    return number(value['weighted']) + ('（历史价）' if value['basis'].startswith('historical') else '')


def main():
    results = formal_results()
    accepted = user_accepted_throughput(results)
    latest = {}
    states = [read(p) for p in ROOT.glob('*-model-state.json')]
    for state in sorted((s for s in states if s), key=lambda s: s.get('started_utc', '')):
        latest[state['model']] = state
    ended = sum(s.get('status') in ('both_stages_completed', 'both_stages_completed_with_limitations')
                for s in latest.values())
    done = sum(chosen(results, model, 'throughput') is not None
               and chosen(results, model, 'sla') is not None for model in PROFILES)
    lines = [
        '# 原五模型评测摘要（历史批次）', '',
        '最新完整结果见[六模型价格、纯吞吐与SLA收入报告](FIVE-MODEL-REVENUE-REPORT.md)。'
        'GLM 5.3 NVFP4已作为第6项加入，原GLM 5.3 FP8保留；下表及40点统计仅对应原五模型批次，不包含NVFP4。', '',
        f'生成时间：{datetime.now(timezone.utc).isoformat()}。按原判据两阶段均通过 {done}/5；已结束流程 {ended}/5（含存在限制的模型）；'
        f'完整正式点 {len(results)}；成功请求 {sum(s["success"] for s in results)}/'
        f'{sum(s["requests"] for s in results)}。测量判定：'
        f'{sum(s["status"] == "PASS" for s in results)} PASS / '
        f'{sum(s["status"] == "FAIL" for s in results)} FAIL；请求成功不等于满足SLA或缓存目标。'
        '运行中数据不进入结果。'
        + ('用户另已接受V4 Pro纯吞吐88.2667%的缓存偏差，现五模型均可列出两档收入；原FAIL不改写，SLA判据不变。'
           if accepted else ''), '',
        '## 统一吞吐档', '',
        '76,800 输入 / 1,024 输出；实际输入缓存目标90%；200条；request_rate=inf；'
        '无客户端并发上限，保留服务端调度上限。以下是完整批次吞吐，非无限时间稳态最大值。', '',
        '| 模型 | H200数 | 成功/请求 | 输入 TPM | 其中命中 TPM | 未命中 TPM | 输出 TPM | 总 TPM | 缓存 % | 单卡30天 USD | 证据 |',
        '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|',
    ]
    if any(s.get('status') == 'paused_by_user' for s in latest.values()):
        lines[2:2] = ['状态：按用户要求暂停，未自动恢复。见[暂停记录](PAUSED-20260913-1657.md)。', '']
    for model, profile in PROFILES.items():
        item = chosen(results, model, 'throughput')
        exception = item is None and model == 'v4pro' and accepted is not None
        if exception:
            item = accepted
        if item:
            label = profile['name'] + ('（用户接受缓存偏差，首轮）' if exception else '')
            values = [label, str(item['gpus']), f'{item["success"]}/{item["requests"]}',
                      *[number(item[key], 0) for key in ('input_tpm', 'cached_input_tpm',
                                                       'uncached_input_tpm', 'output_tpm', 'total_tpm')],
                      number(item['observed_cache_rate']*100, 3), money(item),
                      f'[JSON]({item["evidence"]})']
        else:
            values = [profile['name'], str(profile['gpus']), '未取得有效结果', *['—']*8]
        lines.append('| ' + ' | '.join(values) + ' |')
    lines += ['', '## SLA最高实测通过点', '',
              '同时满足各模型平均TTFT/TPOT、200/200成功、缓存和发压有效性。'
              '无P95门槛；不降低既定SLA。按完成总TPM选择已测通过点。', '',
              '| 模型 | 目标/完成 RPS | TTFT s / 门槛 | TPOT ms / 门槛 | 输入/输出/总 TPM | 缓存 % | 单卡30天 USD | 相邻更高速率失败点 | 证据 |',
              '|---|---|---|---|---|---:|---:|---|---|']
    for model, profile in PROFILES.items():
        item = chosen(results, model, 'sla')
        if item:
            candidates = [s for s in results if s['model'] == model and s['scenario'] == 'sla'
                          and s['status'] == 'FAIL' and s['request_rate'] > item['request_rate']
                          and s['engine_run'] == item['engine_run']
                          and set(s['failure_reasons']).issubset({'TTFT', 'TPOT', 'cache_rate_mismatch'})]
            neighbor = min(candidates, key=lambda s: s['request_rate']) if candidates else None
            fail = (f'{neighbor["request_rate"]:g} RPS：'
                    f'TTFT {neighbor["ttft_s"]["mean"]:.3f}s，TPOT {neighbor["tpot_ms"]["mean"]:.3f}ms '
                    f'[JSON]({neighbor["evidence"]})') if neighbor else '尚未取得失败上界'
            if neighbor and 'cache_rate_mismatch' in neighbor['failure_reasons']:
                fail += f'；缓存{neighbor["observed_cache_rate"]*100:.3f}%超差，非纯延迟上界'
            values = [profile['name'], f'{item["request_rate"]:g} / {item["completed_rps"]:.6f}',
                      f'{item["ttft_s"]["mean"]:.3f} / {"<" if profile.get("ttft_strict") else "≤"}{profile["ttft_s"]:g}',
                      f'{item["tpot_ms"]["mean"]:.3f} / ≤{profile["tpot_ms"]:.3f}',
                      ' / '.join(number(item[key], 0) for key in ('input_tpm', 'output_tpm', 'total_tpm')),
                      number(item['observed_cache_rate']*100, 3), money(item), fail,
                      f'[JSON]({item["evidence"]})']
        else:
            search = read(ROOT / (latest.get(model, {}).get('active_stage', '') + '-search.json'))
            status = ('已测点无达标点' if search.get('status') == 'no_pass_within_search_range'
                      else '尚未取得正式通过点')
            values = [profile['name'], status, *['—']*7]
        lines.append('| ' + ' | '.join(values) + ' |')
    lines += ['', '## 当前执行状态', '', '| 模型 | 状态 | 当前策略/搜索状态 |', '|---|---|---|']
    for model, profile in PROFILES.items():
        state = latest.get(model, {})
        search = read(ROOT / (state.get('active_stage', '') + '-search.json'))
        lines.append(f'| {profile["name"]} | {state.get("status", "尚未开始")} | '
                     f'{state.get("active_stage", "—")} / {search.get("status", "—")} |')
    release = read(ROOT / 'runs/v4pro-resume-12-sla/released.json')
    if (ended == 5 and release.get('gpus_released') and release.get('port_released')
            and not release.get('live_group_pids')):
        lines += ['', f'本轮本地实例已全部结束；最后资源释放时间：{release["utc"]}。'
                  '本任务进程组为空、30480端口释放、8卡显存均1 MiB；线上服务未变更。'
                  '见[资源释放记录](runs/v4pro-resume-12-sla/released.json)。']
    if (ROOT / 'V4PRO-CACHE-REVIEW.md').exists() and not chosen(results, 'v4pro', 'throughput'):
        lines += ['', 'V4 Pro限制：两轮高吞吐均200/200成功，但实际缓存88.2667%，'
                  '未满足原90%目标及预设容差。' +
                  ('用户已接受这一偏差，上表使用首轮实际计量结果；复验总TPM2,735,199、单卡30天2,163.39 USD，'
                   '不混合两轮或挑选较快点。详见[接受记录](v4pro-throughput-user-acceptance.json)及'
                   '[完整收入报告](FIVE-MODEL-REVENUE-REPORT.md)。'
                   if accepted else '不能进入上方有效吞吐/收入表。') +
                  '见[缓存偏差复核](V4PRO-CACHE-REVIEW.md)。']
    if (ROOT / 'V4PRO-SLA-STARTUP-OOM.md').exists() and not chosen(results, 'v4pro', 'sla'):
        resumed = (ROOT / 'RESUMED-20260914.md').exists()
        lines += ['', 'V4 Pro原cookbook低延迟配置在DSPARK CUDA Graph捕获时OOM，'
                  '尚未取得正式SLA通过点。' +
                  ('用户已授权调整mem或图捕获规格，确实无法启动则跳过；卡数与SLA不变。'
                   '见[续跑计划](RESUMED-20260914.md)。' if resumed else
                   '降低图捕获最大batch至64的调整方案仍待用户确认；未改变卡数、参数或SLA。') +
                  '见[启动OOM诊断](V4PRO-SLA-STARTUP-OOM.md)。']
    if (ROOT / 'V4PRO-TUNING.md').exists():
        lines += ['', 'V4 Pro按用户授权单独验证内存/图捕获调整；有效SLA配置为8卡TP8、DSPARK、mem .86、decode graph最大BS32，'
                  '服务端max-running仍为256，graph32不等于客户端并发限制。此结果不代表原cookbook基线已通过。'
                  '统一吞吐扩容尝试在正式前缓存预置发生运行时OOM，原缓存偏差、启动与运行时OOM均保留，'
                  '见[配置调整与验证](V4PRO-TUNING.md)。']
    lines += ['', '## 口径和限制', '',
              '- 原生本地 `/generate`、精确 `input_ids`，不包含线上router/Chat模板开销；未操作线上。',
              '- temperature=0、ignore_eos=true，固定输出总token；随机token可能影响投机接受率，不代表自然业务或模型质量。',
              '- 同一SLA点固定200条，确定性open-loop；最多12点、10%相对或0.005 RPS绝对夹逼精度，无边界重复确认。',
              '- 原实际输入token缓存判据仍为±0.5个百分点；如列用户接受偏差点，按真实缓存率解释，不当作精确目标命中率的容量。SLA缓存超差的高档不能冒称纯延迟上界。',
              '- GPU数按用户确认的8/2/8/8/4。V4 Flash与GLM 5.3 Flash缩卡为用户指定，不冒称cookbook官方已验证缩卡。',
              '- 官网单价与来源见[报告](REPORT.md)。30天满载窗口为[2026-09-13, 2026-10-13) UTC；当前DeepSeek147峰/573谷小时，旧V4 Flash历史情景210峰/510谷小时。',
              '- 单卡收入分别使用实测命中输入、未命中输入、输出TPM乘相应价格，再按30天及实际卡数折算；不是利润，未扣GPU、电力、运维、预热或故障停机成本。',
              '- 不同模型SLA、输入分布、部署策略不同，不能将收入差异解释为纯模型效率排序。',
              '- 所有正式点含失败点见[RESULTS.md](RESULTS.md)；[计量复核](ACCOUNTING-AUDIT.md)；[启动配置](RUNS.md)。', '']
    (ROOT / 'SUMMARY.md').write_text('\n'.join(lines))
    print(json.dumps({'models_completed': done, 'formal_points': len(results)}))


if __name__ == '__main__':
    main()
