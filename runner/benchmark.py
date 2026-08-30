#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

PROTOCOL = '''You are a constrained software-maintenance agent. Return exactly one JSON object per turn, with no markdown.
Allowed actions:
{"action":"list_files"}
{"action":"read_file","path":"relative/path"}
{"action":"write_file","path":"relative/path","content":"complete replacement content"}
{"action":"run_tests"}
{"action":"finish","summary":"short summary"}
Never invent tool results. Read relevant files before editing. Prefer the smallest correct change. Do not touch files outside the workspace. If the task requires a code fix, do not finish until you have written the change and verified that tests pass.'''

WRITE_ALIASES = {"write_file", "edit_file", "fix_file", "replace_file"}


def post_json(url, payload, timeout=180):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def parse_object(text):
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("no JSON object found")
        return json.loads(match.group(0))


def safe_path(root, rel):
    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError("path escapes workspace")
    return candidate


def tree(root):
    items = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.parts:
            items.append(str(path.relative_to(root)))
    return items[:250]


def run_tests(root, command):
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=root, shell=True, text=True, capture_output=True, timeout=120)
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-5000:],
        "stderr": proc.stderr[-5000:],
        "seconds": round(time.perf_counter() - started, 4),
    }


def chat(endpoint, messages, seed, max_tokens):
    started = time.perf_counter()
    data = post_json(endpoint.rstrip("/") + "/v1/chat/completions", {
        "model": "benchmark-model",
        "messages": messages,
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "seed": seed,
    })
    elapsed = time.perf_counter() - started
    choice = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    timings = data.get("timings", {})
    return choice, elapsed, usage, timings


def one_run(source, task_text, skill_text, manifest, endpoint, seed, max_steps, max_tokens, reasoning_mode):
    with tempfile.TemporaryDirectory(prefix="agent-bench-") as td:
        work = Path(td) / "workspace"
        shutil.copytree(source, work)
        test_command = manifest["test_command"]
        editable_paths = set(manifest.get("editable_paths", []))
        baseline = run_tests(work, test_command)
        last_test = baseline
        task_prompt = (
            PROTOCOL
            + f"\n\nSKILL:\n{skill_text}\n\nTASK:\n{task_text}\n\nInitial file tree:\n"
            + "\n".join(tree(work))
        )
        if editable_paths:
            task_prompt += "\n\nOnly these files may be modified:\n" + "\n".join(sorted(editable_paths))
        if reasoning_mode == "no-think":
            task_prompt += "\n\n/no_think"
        messages = [{"role": "user", "content": task_prompt}]
        started = time.perf_counter()
        tool_calls = invalid_actions = writes = model_seconds = 0
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        timing_samples = []
        transcript = []

        for step in range(max_steps):
            raw = ""
            try:
                raw, elapsed, usage, timings = chat(endpoint, messages, seed + step, max_tokens)
                model_seconds += elapsed
                for key in usage_total:
                    usage_total[key] += int(usage.get(key, 0) or 0)
                if timings:
                    timing_samples.append(timings)
                action = parse_object(raw)
            except Exception as exc:
                invalid_actions += 1
                transcript.append({"step": step + 1, "error": str(exc), "raw": raw[:1000]})
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "Invalid response. Return exactly one allowed JSON action and nothing else."})
                continue

            transcript.append({"step": step + 1, "action": action})
            messages.append({"role": "assistant", "content": json.dumps(action)})
            name = action.get("action")
            try:
                if name == "list_files":
                    result = {"files": tree(work)}
                elif name == "read_file":
                    path = safe_path(work, action["path"])
                    result = {"path": action["path"], "content": path.read_text()[:12000]}
                elif name in WRITE_ALIASES:
                    rel = action["path"]
                    if editable_paths and rel not in editable_paths:
                        raise ValueError(f"write blocked by benchmark manifest: {rel}")
                    path = safe_path(work, rel)
                    if not path.exists():
                        raise ValueError("benchmark permits replacement of existing files only")
                    path.write_text(action["content"])
                    writes += 1
                    result = {"ok": True, "path": rel, "normalized_action": "write_file"}
                elif name == "run_tests":
                    last_test = run_tests(work, test_command)
                    result = last_test
                elif name == "finish":
                    if baseline["exit_code"] != 0 and writes == 0:
                        result = {"error": "Cannot finish: no code change has been written. Make the smallest correct change, then verify it."}
                    else:
                        last_test = run_tests(work, test_command)
                        if last_test["exit_code"] != 0:
                            result = {"error": "Cannot finish: tests still fail. Inspect the failure and continue fixing.", "test_result": last_test}
                        else:
                            tool_calls += 1
                            break
                else:
                    invalid_actions += 1
                    result = {"error": "unsupported action; use one of list_files, read_file, write_file, run_tests, finish"}
                tool_calls += 1
            except Exception as exc:
                invalid_actions += 1
                result = {"error": str(exc)}
            messages.append({"role": "user", "content": "TOOL_RESULT:\n" + json.dumps(result)})

        final_test = run_tests(work, test_command)
        changed = []
        for rel in tree(work):
            src = source / rel
            dst = work / rel
            if src.exists() and dst.exists() and src.read_bytes() != dst.read_bytes():
                changed.append(rel)
        return {
            "seed": seed,
            "success": baseline["exit_code"] != 0 and final_test["exit_code"] == 0,
            "baseline_failed": baseline["exit_code"] != 0,
            "wall_seconds": round(time.perf_counter() - started, 4),
            "model_seconds": round(model_seconds, 4),
            "tool_calls": tool_calls,
            "invalid_actions": invalid_actions,
            "writes": writes,
            "changed_files": changed,
            "usage": usage_total,
            "timing_samples": timing_samples,
            "final_test": final_test,
            "transcript": transcript,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--skill", required=True)
    ap.add_argument("--model-key", required=True)
    ap.add_argument("--endpoint", default="http://127.0.0.1:8080")
    ap.add_argument("--repetitions", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=192)
    ap.add_argument("--reasoning-mode", choices=["auto", "no-think"], default="auto")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    fixture = Path(args.fixture)
    manifest = json.loads((fixture / "benchmark.json").read_text())
    task = (fixture / "TASK.md").read_text()
    skill = Path(args.skill).read_text()
    runs = [
        one_run(
            fixture, task, skill, manifest, args.endpoint,
            1000 + i * 101, args.max_steps, args.max_tokens, args.reasoning_mode,
        )
        for i in range(args.repetitions)
    ]
    successes = sum(1 for r in runs if r["success"])
    result = {
        "model": args.model_key,
        "fixture": manifest.get("key"),
        "repetitions": args.repetitions,
        "reasoning_mode": args.reasoning_mode,
        "max_tokens": args.max_tokens,
        "successes": successes,
        "success_rate": successes / max(1, args.repetitions),
        "runs": runs,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("model", "fixture", "repetitions", "successes", "success_rate")}))


if __name__ == "__main__":
    main()
