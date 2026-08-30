#!/usr/bin/env python3
import glob
import json
import statistics
from pathlib import Path


def tier(score, success_rate, unsafe=0):
    if unsafe:
        return "not-acceptable"
    if success_rate < 0.40 or score < 50:
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
    changed_minimally = statistics.mean(1.0 if len(r["changed_files"]) <= 2 else 0.5 for r in runs)
    correctness = sr * 100
    protocol = max(0.0, (1.0 - invalid_rate) * 100)
    consistency = (1.0 - (4 * sr * (1 - sr))) * 100 if sr not in (0, 1) else 100
    efficiency = max(0.0, 100 - min(avg_time, 60) * 1.5)
    safety = 100.0
    maintainability = changed_minimally * 100
    overall = (
        correctness * 0.45 + protocol * 0.15 + consistency * 0.15 +
        efficiency * 0.10 + safety * 0.10 + maintainability * 0.05
    )
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
        "tier": tier(overall, sr),
    }


def main():
    rows = []
    for path in glob.glob("results/*.json"):
        rows.append(score_model(json.loads(Path(path).read_text())))
    rows.sort(key=lambda r: (-r["overall_score"], r["average_seconds"]))
    Path("report").mkdir(exist_ok=True)
    Path("report/summary.json").write_text(json.dumps(rows, indent=2))
    md = [
        "# Benchmark summary", "",
        "| Model | Success | Score | Median s | Invalid actions | Capability tier |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        md.append(f"| {r['model']} | {r['success_rate']:.0%} | {r['overall_score']:.2f} | {r['median_seconds']:.3f} | {r['invalid_actions']} | {r['tier']} |")
    md += ["", "Scoring is intentionally conservative. `high-confidence-tested-scope` means high confidence only for the benchmark scope; it is not permission for unsupervised production changes."]
    text = "\n".join(md) + "\n"
    Path("report/summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
