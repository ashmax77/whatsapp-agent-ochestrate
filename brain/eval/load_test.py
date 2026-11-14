"""
Phase 9 Load & Concurrency Testing Suite.
Simulates 20 concurrent customers interacting simultaneously with the Brain
to verify session isolation, async locking, and latency under load.
"""

import sys
import time
import asyncio
import statistics
import argparse
from typing import List, Dict, Any
import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


async def simulate_customer_journey(client: httpx.AsyncClient, base_url: str, user_index: int) -> Dict[str, Any]:
    user_id = f"sim_load_user_{user_index:03d}"
    latencies: List[float] = []
    errors: int = 0
    final_stage: str = "unknown"

    scripted_turns = [
        {"type": "text", "content": "Hi there!"},
        {"type": "text", "content": "One medium Supreme pizza please"},
        {"type": "text", "content": "Delivery to Cinnamon Gardens"},
        {"type": "text", "content": "Show summary"},
        {"type": "text", "content": "YES confirm my order"},
    ]

    for turn_idx, turn in enumerate(scripted_turns):
        payload = {
            "user_id": user_id,
            "type": turn["type"],
            "content": turn["content"],
            "message_id": f"msg_load_{user_index}_{turn_idx}_{int(time.time()*1000)}",
            "push_name": f"Customer_{user_index}",
            "location": None,
            "audio_b64": None,
            "timestamp": int(time.time()),
        }

        t0 = time.time()
        try:
            resp = await client.post(f"{base_url}/message", json=payload, timeout=20.0)
            elapsed = time.time() - t0
            latencies.append(elapsed)

            if resp.status_code == 200:
                data = resp.json()
                final_stage = data.get("meta", {}).get("stage", "unknown")
            else:
                errors += 1
        except Exception as e:
            errors += 1
            latencies.append(time.time() - t0)

        # Small human inter-turn jitter (50ms - 150ms)
        await asyncio.sleep(0.05 + (user_index % 5) * 0.02)

    return {
        "user_id": user_id,
        "turns": len(scripted_turns),
        "errors": errors,
        "latencies": latencies,
        "final_stage": final_stage,
    }


async def run_load_test(base_url: str = DEFAULT_BASE_URL, concurrency: int = 20) -> Dict[str, Any]:
    print(f"🚀 Starting load test with {concurrency} concurrent customers against {base_url}...")
    t_start = time.time()

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=100, max_keepalive_connections=50)) as client:
        # Check health first
        try:
            h = await client.get(f"{base_url}/health", timeout=5.0)
            if h.status_code != 200:
                print(f"❌ Server at {base_url} returned health status {h.status_code}")
                return {"error": "Server unhealthy"}
        except Exception as e:
            print(f"❌ Could not connect to {base_url}: {e}")
            return {"error": str(e)}

        tasks = [simulate_customer_journey(client, base_url, i) for i in range(concurrency)]
        results = await asyncio.gather(*tasks)

    total_duration = time.time() - t_start
    all_latencies = [l for r in results for l in r["latencies"]]
    total_errors = sum(r["errors"] for r in results)
    total_turns = sum(r["turns"] for r in results)

    all_latencies.sort()
    n = len(all_latencies)
    p50 = statistics.median(all_latencies) if all_latencies else 0.0
    p95 = all_latencies[int(min(n - 1, n * 0.95))] if all_latencies else 0.0
    p99 = all_latencies[int(min(n - 1, n * 0.99))] if all_latencies else 0.0
    avg = statistics.mean(all_latencies) if all_latencies else 0.0

    print("\n" + "=" * 50)
    print("📊 LOAD TEST RESULTS")
    print("=" * 50)
    print(f"Concurrency:       {concurrency} simulated users")
    print(f"Total Requests:    {total_turns}")
    print(f"Total Duration:    {total_duration:.2f} s")
    print(f"Throughput:        {total_turns / total_duration:.1f} req/s")
    print(f"Error Rate:        {total_errors} / {total_turns} ({(total_errors/max(1, total_turns))*100:.1f}%)")
    print(f"Latency p50:       {p50*1000:.1f} ms")
    print(f"Latency p95:       {p95*1000:.1f} ms")
    print(f"Latency p99:       {p99*1000:.1f} ms")
    print(f"Latency avg:       {avg*1000:.1f} ms")
    print("=" * 50)

    return {
        "concurrency": concurrency,
        "total_requests": total_turns,
        "total_errors": total_errors,
        "duration_sec": total_duration,
        "rps": round(total_turns / total_duration, 2),
        "latency_p50_ms": round(p50 * 1000, 1),
        "latency_p95_ms": round(p95 * 1000, 1),
        "latency_p99_ms": round(p99 * 1000, 1),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run concurrent load testing against Pizza Agent Brain")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Brain API base URL")
    parser.add_argument("--concurrency", type=int, default=20, help="Number of concurrent customers (default: 20)")
    args = parser.parse_args()

    asyncio.run(run_load_test(base_url=args.url, concurrency=args.concurrency))
