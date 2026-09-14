"""Early promotion only after the first 100 scheduled requests finish."""
import asyncio
import math
import time


def early_decision(rows, profile, hit, rate, minimum=100):
    by_id = {r['id']: r for r in rows}
    if any(i not in by_id for i in range(minimum)):
        return None
    prefix = [by_id[i] for i in range(minimum)]
    failures = []
    if not all(r.get('success') for r in prefix):
        failures.append('request_failure')
        return {'eligible': False, 'reasons': failures, 'first_scheduled_requests': minimum}
    ttft = sum(r['ttft_s'] for r in prefix) / minimum
    tpot = sum(r['tpot_ms'] for r in prefix) / minimum
    if (ttft >= profile['ttft_s'] if profile.get('ttft_strict') else ttft > profile['ttft_s']):
        failures.append('TTFT')
    if tpot > profile['tpot_ms']:
        failures.append('TPOT')
    cache_known = all(isinstance(r.get('cached_tokens'), int) for r in prefix)
    observed_hit = sum(r['cached_tokens'] for r in prefix) / sum(r['input_tokens'] for r in prefix) if cache_known else None
    if observed_hit is None or abs(observed_hit-hit) > .005:
        failures.append('cache_rate_mismatch')
    starts = sorted(r['start_clock'] for r in prefix)
    offered = (minimum-1)/(starts[-1]-starts[0]) if starts[-1] > starts[0] else None
    if offered is None or offered < rate*.95:
        failures.append('client_offered_rate_shortfall')
    return {'eligible': not failures, 'reasons': failures, 'first_scheduled_requests': minimum,
            'mean_ttft_s': ttft, 'mean_tpot_ms': tpot, 'cache_rate': observed_hit,
            'actual_offered_rps': offered}


async def dispatch(n, rate, send, on_result, check=None):
    """Uncapped deterministic open-loop; never cancel an already sent request."""
    begun = time.perf_counter()
    rows, submitted, tasks = [], set(), []
    decision = None
    stop_new = False

    async def one(i):
        nonlocal decision, stop_new
        planned = begun if math.isinf(rate) else begun+i/rate
        await asyncio.sleep(max(0, planned-time.perf_counter()))
        if stop_new:
            return
        submitted.add(i)
        row = await send(i, planned)
        rows.append(row)
        on_result(row, rows, time.perf_counter()-begun)
        if check and decision is None:
            checked = check(rows)
            if checked is not None:
                decision = {**checked, 'elapsed_s_at_check': time.perf_counter()-begun,
                            'submitted_at_check': len(submitted)}
                if decision['eligible']:
                    stop_new = True
                    for j, task in enumerate(tasks):
                        if j not in submitted and not task.done():
                            task.cancel()

    tasks = [asyncio.create_task(one(i)) for i in range(n)]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
            raise outcome
    assert len(rows) == len(submitted), 'Every submitted request must drain'
    return rows, time.perf_counter()-begun, {
        'planned_maximum': n, 'submitted_requests': len(submitted),
        'unsent_requests': n-len(submitted), 'early_stopped': stop_new,
        'decision': decision, 'all_inflight_drained': True}
