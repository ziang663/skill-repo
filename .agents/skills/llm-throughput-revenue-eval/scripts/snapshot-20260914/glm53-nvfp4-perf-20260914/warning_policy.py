"""Separate recoverable allocator warning logs from runtime error evidence."""
import re


def classify_log(log):
    matches, warnings, errors = [], [], []
    for line in log.splitlines():
        if not re.search(r'OutOfMemoryError|CUDA out of memory|memory allocation failed|Scheduler hit an exception|Traceback \(most recent call last\)', line):
            continue
        line = line[:2000]
        matches.append(line)
        allocator_warning = re.search(
            r'\[W[^\]]*CUDACachingAllocator\.cpp:\d+\] memory allocation failed with OOM', line)
        if allocator_warning and not re.search(r'OutOfMemoryError|Traceback|Scheduler hit', line):
            warnings.append(line)
        else:
            errors.append(line)
    return {'matches': matches, 'allocator_warnings': warnings, 'runtime_errors': errors}
