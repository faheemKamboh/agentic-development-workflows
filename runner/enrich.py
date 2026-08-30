#!/usr/bin/env python3
import argparse
import json
import re
import statistics
from pathlib import Path

UNITS = {
    'B': 1 / (1024 * 1024),
    'KB': 1000 / (1024 * 1024),
    'KIB': 1 / 1024,
    'MB': 1000 * 1000 / (1024 * 1024),
    'MIB': 1,
    'GB': 1000 * 1000 * 1000 / (1024 * 1024),
    'GIB': 1024,
}


def memory_to_mb(value):
    value = value.strip().upper()
    m = re.match(r'([0-9.]+)\s*([KMGT]?I?B)', value)
    if not m:
        return None
    return float(m.group(1)) * UNITS.get(m.group(2), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--result', required=True)
    ap.add_argument('--resources', required=True)
    ap.add_argument('--startup', required=True)
    args = ap.parse_args()

    result_path = Path(args.result)
    data = json.loads(result_path.read_text())
    startup_path = Path(args.startup)
    startup = json.loads(startup_path.read_text()) if startup_path.exists() else {}

    cpu_samples, memory_samples = [], []
    resource_path = Path(args.resources)
    if resource_path.exists():
        for line in resource_path.read_text(errors='replace').splitlines():
            try:
                _, payload = line.split('\t', 1)
                sample = json.loads(payload)
            except Exception:
                continue
            try:
                cpu_samples.append(float(str(sample.get('CPUPerc', '')).rstrip('%')))
            except Exception:
                pass
            mb = memory_to_mb(str(sample.get('MemUsage', '')).split('/', 1)[0].strip())
            if mb is not None:
                memory_samples.append(mb)

    wall_seconds = [float(r.get('wall_seconds', 0) or 0) for r in data.get('runs', [])]
    predicted_n = predicted_ms = prompt_n = prompt_ms = 0.0
    for run in data.get('runs', []):
        for sample in run.get('timing_samples', []):
            predicted_n += float(sample.get('predicted_n', 0) or 0)
            predicted_ms += float(sample.get('predicted_ms', 0) or 0)
            prompt_n += float(sample.get('prompt_n', 0) or 0)
            prompt_ms += float(sample.get('prompt_ms', 0) or 0)

    data['metrics'] = {
        'model_load_ms': startup.get('model_load_ms'),
        'model_sha256': startup.get('model_sha256'),
        'peak_memory_mb': round(max(memory_samples), 2) if memory_samples else None,
        'average_memory_mb': round(statistics.mean(memory_samples), 2) if memory_samples else None,
        'average_cpu_percent': round(statistics.mean(cpu_samples), 2) if cpu_samples else None,
        'peak_cpu_percent': round(max(cpu_samples), 2) if cpu_samples else None,
        'median_run_seconds': round(statistics.median(wall_seconds), 4) if wall_seconds else None,
        'average_run_seconds': round(statistics.mean(wall_seconds), 4) if wall_seconds else None,
        'decode_tokens_per_second': round(predicted_n / (predicted_ms / 1000), 3) if predicted_ms else None,
        'prompt_tokens_per_second': round(prompt_n / (prompt_ms / 1000), 3) if prompt_ms else None,
        'resource_samples': len(memory_samples),
    }
    result_path.write_text(json.dumps(data, indent=2))


if __name__ == '__main__':
    main()
