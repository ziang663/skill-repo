"""Regenerate derived result tables; never modify raw benchmark evidence."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import shlex
import re

ROOT = Path(__file__).resolve().parent
PROFILES = json.loads((ROOT / "profiles.json").read_text())
PRICES = json.loads((ROOT / "prices.json").read_text())


def peak_hours(schedule):
    if schedule == "flat":
        return 0
    start = datetime.fromisoformat(PRICES["window_start_utc"])
    return sum(7 for d in range(PRICES["days"])
               if schedule.startswith("daily_") or (start + timedelta(days=d)).weekday() < 5)


def revenue(summary):
    p = PRICES["models"][summary["model"]]
    fields = ("cached_input_tpm", "uncached_input_tpm", "output_tpm")
    if any(summary.get(f) is None for f in fields):
        return None
    tpm = [summary[f] for f in fields]
    hours = PRICES["days"] * 24
    def calc(prices):
        return sum(a*b for a, b in zip(tpm, prices))*60*hours/1e6/summary["gpus"]
    if "flat" in p:
        return {"weighted": calc(p["flat"]), "basis": p["basis"], "currency": "USD"}
    peak = peak_hours(p["schedule"])
    weighted = [(a*peak+b*(hours-peak))/hours for a, b in zip(p["peak"], p["offpeak"])]
    return {"weighted": calc(weighted), "all_peak": calc(p["peak"]),
            "all_offpeak": calc(p["offpeak"]), "peak_hours": peak,
            "offpeak_hours": hours-peak, "basis": p["basis"], "currency": "USD"}


def number(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


def main():
    from engine_evidence import collect
    collect()
    summaries = []
    for path in sorted((ROOT / "benchmarks").glob("*/summary.json")):
        s = json.loads(path.read_text())
        s["evidence"] = str(path.relative_to(ROOT))
        s["revenue"] = revenue(s)
        summaries.append(s)
    lines = ["# 实测结果（自动汇总）", "",
             "本表只收录已完成的测量；运行中及启动失败不产生能力数值。RPS 为整批实际成功完成数/总时长，含填充与排空。", "",
             "收入按实际缓存命中计量、实际卡数和 30 天满载折算，是理论收入而非利润。FAIL 行不作为达标容量或收入推荐。", "",
             "| 模型 | 阶段 | 卡数 | 目标 RPS | 完成/请求 | 状态/原因 | 实际 RPS | Mean TTFT s | Mean TPOT ms | 缓存 % | 输入 TPM | 输出 TPM | 总 TPM | 单卡月收入 USD | 证据 |",
             "|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for s in summaries:
        r = s["revenue"]
        formal = s["requests"] == 200
        label = s["scenario"] + ("" if formal else " 诊断")
        rate = s["request_rate"]
        saturation = isinstance(rate, (int, float)) and s["completed_rps"] < .9*rate
        reasons = ",".join(s["failure_reasons"])
        status = s["status"] + (f" ({reasons})" if reasons else "")
        if saturation:
            status += "；完成率<目标90%（含排空）"
        money = number(r["weighted"]) if r and s["status"] == "PASS" and formal else "—"
        if r and r["basis"].startswith("historical") and money != "—":
            money += "（历史价情景）"
        values = [PROFILES[s["model"]]["name"], label, str(s["gpus"]), str(rate),
                  f'{s["success"]}/{s["requests"]}', status, number(s["completed_rps"], 4),
                  number(s["ttft_s"]["mean"] if s["ttft_s"] else None, 3),
                  number(s["tpot_ms"]["mean"] if s["tpot_ms"] else None, 3),
                  number(s["observed_cache_rate"]*100 if s["observed_cache_rate"] is not None else None, 3),
                  number(s["input_tpm"], 0), number(s["output_tpm"], 0), number(s["total_tpm"], 0),
                  money, f'[JSON]({s["evidence"]})']
        lines.append("| " + " | ".join(values) + " |")
    lines += ["", "## 计费边界", "",
              "- 统一 USD；GLM 使用 Z.ai 国际站官方价，不换算为人民币站价格。",
              "- 当前 DeepSeek 峰时仅周一至周五 UTC 01–04、06–10；2026-09-13 至 2026-10-13 共 147 峰时小时、573 谷时小时。",
              "- V4 Flash 已退役，采用 2026-08-13 官方图片公告的历史价格作情景估值；该公告列每日 7 小时峰时，故历史情景为 210/510 小时。不能作为当前官方在售收入承诺。",
              "- 原始计量的命中、未命中、输出 TPM 及全峰价/全谷价情景保存在 `results-derived.json`。",
              "- 有限批次完成 RPS 低于目标也可能包含排空影响，不能仅凭这一项断言稳态已饱和；SLA 仍以均值及请求成功、发压/缓存有效性判断。", ""]
    (ROOT / "RESULTS.md").write_text("\n".join(lines))
    (ROOT / "results-derived.json").write_text(json.dumps(summaries, indent=2, ensure_ascii=False)+"\n")
    launch_lines = ["# 启动原始配置", "", "命令与环境来自每代 `launch.json`；有效参数以对应 `server-info.json` 与 `engine.log` 为准。", ""]
    for run in sorted((ROOT / "runs").glob("*")):
        path = run / "launch.json"
        if not path.exists():
            continue
        launch = json.loads(path.read_text())
        launch_lines += [f"## {run.name}", "", f'来源：`{launch["source"]}`；commit `{launch["source_commit"]}`。', "",
                         "```bash", shlex.join(["env", *[f"{k}={v}" for k,v in launch["env"].items()], *launch["argv"]]), "```", "",
                         f'[启动记录](runs/{run.name}/launch.json) · [引擎日志](runs/{run.name}/engine.log)', ""]
    (ROOT / "RUNS.md").write_text("\n".join(launch_lines))
    formal = [s for s in summaries if s["requests"] == 200]
    ht_pass = {s["model"] for s in formal if s["scenario"] == "throughput" and s["status"] == "PASS"}
    searches = []
    for path in ROOT.glob("*-search.json"):
        try:
            searches.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            pass
    bracketed = {s["model"] for s in searches if s.get("status") == "bracketed"}
    resource_bracketed = {s["model"] for s in searches if s.get("status") == "resource_limited_bracket"}
    states = []
    for path in ROOT.glob("*-model-state.json"):
        try:
            states.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            pass
    latest = {}
    for state in sorted(states, key=lambda s: s.get('started_utc', '')):
        latest[state['model']] = state
    active = [f'{s["model"]}: {s["status"]}' for s in latest.values()
              if s['status'] not in ('both_stages_completed', 'both_stages_completed_with_limitations')]
    limited = [s['model'] for s in latest.values() if s.get('limitations')]
    overview = (f"已完成 {len(formal)} 个正式测量点；最大吞吐档通过 {len(ht_pass)}/5 个模型，SLA 通过/失败边界已夹逼 {len(bracketed)}/5 个模型。"
                + (f"另有 {len(resource_bracketed)} 个模型完成受缓存约束的可用速率区间定位，最高通过点有效，但高档不是纯延迟上界。" if resource_bracketed else "")
                + ("当前记录："+"；".join(active)+"。" if active else "")
                + ("已确认限制："+"、".join(limited)+"统一档缓存目标未达成，原FAIL保留。" if limited else "")
                + " 启动/预检失败及未完整完成的尝试不产生性能结论。详见 [实测结果](RESULTS.md)。")
    report = ROOT/"REPORT.md"
    content = report.read_text()
    content = re.sub(r"<!-- live-results:start -->.*?<!-- live-results:end -->",
                     "<!-- live-results:start -->\n"+overview+"\n<!-- live-results:end -->", content, flags=re.S)
    report.write_text(content)
    from summarize_campaign import main as compact_summary
    compact_summary()
    print(json.dumps({"completed_points": len(summaries), "peak_hours_current": peak_hours("weekdays_01_04_06_10_utc")}))


if __name__ == "__main__":
    main()
