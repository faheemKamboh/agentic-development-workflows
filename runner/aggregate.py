#!/usr/bin/env python3
import glob
import json
import statistics
from pathlib import Path


def tier(score, success_rate, unsafe=0):
    if unsafe or success_rate < 0.40:
        return "not-acceptable"
    if success_rate < 0.60 or score < 65:
        return "barely-acceptable"
    if success_rate < 0.80 or score < 78:
        return "close-to-expectations"
    if success_rate < 0.90 or score < 90:
        return "limited-usage"
    return "high-confidence-tested-scope"


def score_model(data):
    runs = data["runs"]
    sr = data["success_rate"]
    invalid = sum(r["invalid_actions"] for r in runs)
    tool_calls = sum(r["tool_calls"] for r in runs)
    invalid_rate = invalid / max(1, tool_calls + invalid)
    avg_time = statistics.mean(r["wall_seconds"] for r in runs)
    median_time = statistics.median(r["wall_seconds"] for r in runs)
    successful = [r for r in runs if r["success"]]
    minimal_scope = statistics.mean(
        1.0 if len(r["changed_files"]) <= 2 else 0.5 for r in successful
    ) if successful else 0.0

    correctness = sr * 100
    protocol = max(0.0, (1.0 - invalid_rate) * 100)
    consistency = sr * 100
    efficiency = max(0.0, 100 - min(avg_time, 90) * 1.0)
    scope = minimal_scope * 100

    overall = (
        correctness * 0.60 + protocol * 0.10 + consistency * 0.15 +
        efficiency * 0.10 + scope * 0.05
    )
    if sr == 0:
        overall = min(overall, 29.99)

    metrics = data.get("metrics", {})
    return {
        "model": data["model"],
        "success_rate": round(sr, 3),
        "overall_score": round(overall, 2),
        "correctness": round(correctness, 2),
        "protocol": round(protocol, 2),
        "consistency": round(consistency, 2),
        "efficiency": round(efficiency, 2),
        "median_seconds": round(median_time, 3),
        "average_seconds": round(avg_time, 3),
        "invalid_actions": invalid,
        "peak_memory_mb": metrics.get("peak_memory_mb"),
        "average_cpu_percent": metrics.get("average_cpu_percent"),
        "tier": tier(overall, sr),
    }


def main():
    rows = []
    for path in glob.glob("results/*.json"):
        data = json.loads(Path(path).read_text())
        if "runs" in data and "success_rate" in data:
            rows.append(score_model(data))
    rows.sort(key=lambda r: (-r["success_rate"], -r["overall_score"], r["average_seconds"]))
    Path("report").mkdir(exist_ok=True)
    Path("report/summary.json").write_text(json.dumps(rows, indent=2))
    md = [
        "# Benchmark summary", "",
        "| Model | Success | Score | Median s | Peak MB | Invalid | Capability tier |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        peak = "-" if r["peak_memory_mb"] is None else f'{r["peak_memory_mb"]:.0f}'
        md.append(f"| {r['model']} | {r['success_rate']:.0%} | {r['overall_score']:.2f} | {r['median_seconds']:.3f} | {peak} | {r['invalid_actions']} | {r['tier']} |")
    md += ["", "Selection is correctness-first. A consistently failing model cannot receive a useful tier merely for protocol compliance or speed."]
    text = "\n".join(md) + "\n"
    Path("report/summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
