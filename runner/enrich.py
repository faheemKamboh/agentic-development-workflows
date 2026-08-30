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

    cpu_samples = []
    memory_samples = []
    resource_path = Path(args.resources)
    if resource_path.exists():
        for line in resource_path.read_text(errors='replace').splitlines():
            try:
                _, payload = line.split('\t', 1)
                sample = json.loads(payload)
            except Exception:
                continue
            cpu = str(sample.get('CPUPerc', '')).rstrip('%')
            try:
                cpu_samples.append(float(cpu))
            except Exception:
                pass
            usage = str(sample.get('MemUsage', '')).split('/', 1)[0].strip()
            mb = memory_to_mb(usage)
            if mb is not None:
                memory_samples.append(mb)

    model_seconds = [float(r.get('model_seconds', 0) or 0) for r in data.get('runs', [])]
    wall_seconds = [float(r.get('wall_seconds', 0) or 0) for r in data.get('runs', [])]
    total_output_tokens = sum(int(r.get('usage', {}).get('completion_tokens', 0) or 0) for r in data.get('runs', []))
    total_model_seconds = sum(model_seconds)

    data['metrics'] = {
        'model_load_ms': startup.get('model_load_ms'),
        'peak_memory_mb': round(max(memory_samples), 2) if memory_samples else None,
        'average_memory_mb': round(statistics.mean(memory_samples), 2) if memory_samples else None,
        'average_cpu_percent': round(statistics.mean(cpu_samples), 2) if cpu_samples else None,
        'peak_cpu_percent': round(max(cpu_samples), 2) if cpu_samples else None,
        'median_run_seconds': round(statistics.median(wall_seconds), 4) if wall_seconds else None,
        'average_run_seconds': round(statistics.mean(wall_seconds), 4) if wall_seconds else None,
        'output_tokens_per_second': round(total_output_tokens / total_model_seconds, 3) if total_model_seconds and total_output_tokens else None,
        'resource_samples': len(memory_samples),
    }
    result_path.write_text(json.dumps(data, indent=2))


if __name__ == '__main__':
    main()
