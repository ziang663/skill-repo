"""Read-only checks of the consolidated report against saved benchmark evidence."""
import hashlib
import json
from pathlib import Path
import re
import unittest

from report_results import PRICES, revenue
from summarize_campaign import formal_results


ROOT = Path(__file__).resolve().parent
REPORT = ROOT / 'FIVE-MODEL-REVENUE-REPORT.md'
NVFP4 = ROOT.parent / 'glm53-nvfp4-perf-20260914'
MODELS = ['v41', 'v4flash', 'v4pro', 'glm53', 'glm53flash', 'glm53_nvfp4']


def read(path):
    return json.loads(path.read_text())


def table_after(text, marker):
    """Return the first Markdown table's cells after an unambiguous heading."""
    lines = text.split(marker, 1)[1].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('|'))
    rows = []
    for line in lines[start:]:
        if not line.startswith('|'):
            break
        rows.append([cell.strip() for cell in line.strip('|').split('|')])
    return rows[0], rows[2:]


def evidence(row):
    return ROOT / re.search(r'\]\(([^)]+)\)', row[0]).group(1)


def monthly(summary):
    if summary['model'] != 'glm53_nvfp4':
        return revenue(summary)['weighted']
    # Independent use of the dated Z.ai GLM 5.3 pricing scenario.
    prices = read(NVFP4 / 'final-audit.json')['prices_usd_per_million']
    total = sum(summary[f'{key}_tpm'] * prices[key]
                for key in ('cached_input', 'uncached_input', 'output'))
    return total * 43200 / 1e6 / summary['gpus']


class SixModelReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = REPORT.read_text()

    def test_six_entries_in_every_main_table(self):
        self.assertTrue(self.text.startswith('# 六模型'))
        for marker in ('## 1.', '表 2：', '表 3：', '表 4：', '## 5.'):
            with self.subTest(table=marker):
                header, rows = table_after(self.text, marker)
                self.assertEqual(len(rows), 6)
                self.assertTrue(all(len(row) == len(header) for row in rows))
                self.assertIn('GLM 5.3 NVFP4', rows[-1][0])

    def test_official_price_columns_include_cache_split(self):
        header, rows = table_after(self.text, '## 1.')
        self.assertEqual(header[1:4], ['未命中输入价格', '命中输入价格', '输出价格'])
        for model, row in zip(MODELS, rows):
            price = PRICES['models']['glm53' if model == 'glm53_nvfp4' else model]
            if 'flat' in price:
                expected = [f'{price["flat"][i]:.3f}' for i in (1, 0, 2)]
            else:
                expected = [f'{price["peak"][i]:.3f} / {price["offpeak"][i]:.3f}'
                            for i in (1, 0, 2)]
            self.assertEqual(row[1:4], expected, model)
        self.assertIn('不是独立官方NVFP4 SKU', rows[-1][-1])

    def test_throughput_numbers_and_revenues(self):
        _, rows = table_after(self.text, '表 2：')
        for model, row in zip(MODELS, rows):
            s = read(evidence(row))
            self.assertEqual(s['model'], model)
            self.assertEqual(s['request_rate'], 'inf')
            self.assertEqual((s['requests'], s['success']), (200, 200))
            self.assertEqual(row[1], str(s['gpus']))
            self.assertEqual(row[2:5], [f'{s[k]:,.0f}' for k in
                                       ('input_tpm', 'output_tpm', 'total_tpm')])
            self.assertEqual(row[5], f'{s["observed_cache_rate"] * 100:.3f}%')
            amount = monthly(s)
            self.assertEqual(row[6:8], [f'{amount:,.2f}', f'{amount * s["gpus"]:,.2f}'])

    def test_sla_numbers_samples_and_revenues(self):
        _, rows = table_after(self.text, '表 4：')
        for model, row in zip(MODELS, rows):
            s = read(evidence(row))
            self.assertEqual((s['model'], s['scenario'], s['status']), (model, 'sla', 'PASS'))
            self.assertEqual(s['requests'], s['success'])
            self.assertEqual(row[1], str(s['gpus']))
            self.assertEqual(row[2], f'{s["success"]}/{s["requests"]}')
            target, completed = map(float, row[3].split(' / '))
            self.assertEqual(target, s['request_rate'])
            self.assertAlmostEqual(completed, s['completed_rps'], places=6)
            self.assertEqual(row[4:7], [f'{s["ttft_s"]["mean"]:.3f}',
                                       f'{s["tpot_ms"]["mean"]:.3f}', f'{s["total_tpm"]:,.0f}'])
            amount = monthly(s)
            self.assertEqual(row[7:9], [f'{amount:,.2f}', f'{amount * s["gpus"]:,.2f}'])
        best = read(evidence(rows[-1]))
        self.assertEqual(best['requests'], 119)
        self.assertTrue(best['adaptive_sampling']['all_inflight_drained'])

    def test_nvfp4_audit_counts_and_preserved_hashes(self):
        original = formal_results()
        self.assertEqual(len(original), 40)
        self.assertEqual(sum(s['success'] for s in original), 8000)
        self.assertEqual(sum(s['status'] == 'PASS' for s in original), 23)
        audit = read(NVFP4 / 'final-audit.json')
        self.assertEqual(audit['status'], 'verified')
        self.assertEqual(sum(p['requests'] for p in audit['points']), 1023)
        for point in audit['points']:
            path = NVFP4 / 'benchmarks' / point['point'] / 'summary.json'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), point['summary_sha256'])
        review = read(NVFP4 / 'throughput-reassessment-20260914.json')
        self.assertEqual(review['status'], 'PASS_WITH_WARNING')
        path = NVFP4 / 'benchmarks' / review['point'] / 'summary.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), review['source_sha256']['summary.json'])
        self.assertEqual(read(path)['status'], 'FAIL')
        self.assertEqual(len(original) + len(audit['points']) + 1, 47)
        self.assertIn('47点、9,223/9,223请求成功', self.text)
        self.assertIn('1,062,592', self.text)
        self.assertIn('588,608', self.text)
        self.assertIn('100–200条自适应收尾规则', self.text)

    def test_relative_evidence_links_exist(self):
        links = re.findall(r'\]\(([^)]+)\)', self.text)
        for link in links:
            if not link.startswith(('https://', 'http://', '#')):
                with self.subTest(link=link):
                    self.assertTrue((ROOT / link.split('#', 1)[0]).exists())

    def test_historical_entrypoints_link_to_six_model_report(self):
        for name in ('REPORT.md', 'SUMMARY.md', 'summarize_campaign.py'):
            content = (ROOT / name).read_text()
            self.assertIn('六模型价格、纯吞吐与SLA收入报告', content)
            self.assertIn('FIVE-MODEL-REVENUE-REPORT.md', content)


if __name__ == '__main__':
    unittest.main()
