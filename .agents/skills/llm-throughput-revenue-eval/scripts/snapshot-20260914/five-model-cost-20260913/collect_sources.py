"""Capture public official documentation without credentials or browser dependencies."""
import concurrent.futures
import datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
SOURCES = {
    "deepseek-pricing": "https://api-docs.deepseek.com/quick_start/pricing",
    "deepseek-pricing-cny": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing",
    "zai-pricing": "https://docs.z.ai/guides/overview/pricing",
    "bigmodel-pricing": "https://docs.bigmodel.cn/cn/guide/models/llm/glm-5.3",
    "cookbook-v41": "https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4_1",
    "cookbook-v41-md": "https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4_1.md",
    "cookbook-v4-md": "https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4.md",
    "cookbook-glm53-md": "https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3.md",
    "cookbook-glm53flash-md": "https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3-Flash.md",
}


class Extract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "a":
            self.links += [v for k, v in attrs if k == "href"]
        if tag in ("p", "div", "tr", "li", "pre", "h1", "h2", "h3", "br"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def capture(item):
    name, url = item
    out = ROOT / "sources"
    out.mkdir(exist_ok=True)
    meta = {"url": url, "retrieved_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as response:
            raw = response.read()
            meta.update(status=response.status, final_url=response.url)
        meta["sha256"] = hashlib.sha256(raw).hexdigest()
        (out / (name + ".html")).write_bytes(raw)
        parser = Extract()
        if url.endswith(".md"):
            text = raw.decode("utf-8", errors="replace")
        else:
            parser.feed(raw.decode("utf-8", errors="replace"))
            text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
        (out / (name + ".txt")).write_text(text)
        meta["links"] = parser.links
        print(json.dumps({"source": name, "status": meta["status"], "bytes": len(raw), "text": text[:3000]}, ensure_ascii=False), flush=True)
    except Exception as exc:
        meta["error"] = repr(exc)
        print(json.dumps({"source": name, "error": repr(exc)}), flush=True)
    (out / (name + ".json")).write_text(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(capture, SOURCES.items()))
