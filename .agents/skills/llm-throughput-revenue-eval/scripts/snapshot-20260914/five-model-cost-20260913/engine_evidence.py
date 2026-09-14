"""Extract concrete deployment evidence; preserve missing/ambiguous memory values."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def collect():
    records = []
    keys = ("tp_size", "ep_size", "dp_size", "pp_size", "enable_dp_attention", "dtype", "quantization",
            "kv_cache_dtype", "mem_fraction_static", "attention_backend", "dsa_prefill_backend", "dsa_decode_backend",
            "moe_runner_backend", "speculative_algorithm", "speculative_num_steps", "speculative_eagle_topk",
            "speculative_num_draft_tokens", "max_total_num_tokens", "max_req_input_len", "max_running_requests",
            "effective_max_running_requests_per_dp", "chunked_prefill_size", "max_prefill_tokens", "page_size",
            "disable_radix_cache", "disable_chunked_prefix_cache", "context_length", "cuda_graph_config",
            "uses_mamba_radix_cache", "mamba_radix_cache_strategy", "mamba_track_interval",
            "max_mamba_cache_size", "mamba_full_memory_ratio", "mamba_ssm_dtype",
            "enable_decoder_swa_bounded_replay")
    pattern = re.compile(r"Load weight end|Memory pool end|KV Cache is allocated|Mamba Cache is allocated|DSV4 (memory calculation|pool sizes|SWA sizing)|max_total_num_tokens=|max_running_requests is capped|Setting KV cache dtype|Capture .* CUDA graph begin|CUDA graph.*(end|finish|mem)|The server is fired up")
    for run in sorted((ROOT/"runs").glob("*")):
        if not (run/"launch.json").exists():
            continue
        launch = json.loads((run/"launch.json").read_text())
        info_path = run/"server-info.json"
        if not info_path.exists():
            continue
        info = json.loads(info_path.read_text())
        base = info.get("server_args", info)
        states = info.get("internal_states", [])
        resolved = {**base, **(states[0] if states else {})}
        lines = []
        if (run/"engine.log").exists():
            with (run/"engine.log").open(errors="replace") as log:
                lines = [line.rstrip() for line in log if pattern.search(line) and "server_args=" not in line]
        (run/"memory-evidence.txt").write_text("\n".join(lines)+"\n")
        cfg = json.loads((Path(launch["profile"]["model_path"])/"config.json").read_text())
        text = cfg.get("text_config", cfg)
        full = resolved.get("max_total_num_tokens", info.get("max_total_num_tokens"))
        declared = text.get("max_position_embeddings")
        dsv4_bytes = next((float(m.group(1)) for l in lines if (m:=re.search(r"bytes_per_full_token=([0-9.]+)", l))), None)
        record = {"run": run.name, "model": launch["model"], "strategy": launch["strategy"],
                  "source_commit": launch["source_commit"], "version": info.get("version"),
                  "effective": {k:resolved.get(k) for k in keys}, "declared_context": declared,
                  "full_token_capacity": full,
                  "pool_to_declared_ratio": full/declared if full and declared else None,
                  "input_cap_from_server": info.get("max_req_input_len"),
                  "memory_per_scheduler": [s.get("memory_usage") for s in states],
                  "startup_per_scheduler": [s.get("startup_time") for s in states],
                  "dsv4_bytes_per_full_token": dsv4_bytes,
                  "model_quantization_config": text.get("quantization_config", cfg.get("quantization_config")),
                  "limits": ["KV capacity is not proof of long-context generation availability.",
                             "Zero/missing kvcache telemetry is not zero allocated memory.",
                             "DSV4 compressed full-token slope excludes fixed SWA/state pools; do not use naive full-attention KV formula."]}
        (run/"engine-evidence.json").write_text(json.dumps(record, indent=2)+"\n")
        records.append(record)
    (ROOT/"engine-evidence.json").write_text(json.dumps(records, indent=2)+"\n")
    return records


if __name__ == "__main__":
    print(json.dumps({"collected_runs": len(collect())}))
