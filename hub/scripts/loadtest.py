"""Lab 7, Task 4: concurrency stress test and connection-pool profiling.

Fires N requests with C concurrent clients at the running server and samples the
pool statistics from /api/v1/health while the load runs. A healthy pool shows:
  * pool_size never above DB_POOL_MAX (connections are reused, not opened per request)
  * connections_num (total ever opened) staying close to pool_max
  * requests_waiting returning to 0 and pool_available returning to pool_size afterwards (no leaks)

    python -m scripts.loadtest --url https://localhost:8443 --requests 3000 --concurrency 100
"""
import argparse
import asyncio
import statistics
import time

import httpx


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://localhost:8443")
    ap.add_argument("--requests", type=int, default=3000)
    ap.add_argument("--concurrency", type=int, default=100)
    ap.add_argument("--path", default="/api/v1/events?per_page=12")
    args = ap.parse_args()

    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.url, verify=False, limits=limits, timeout=30) as client:
        before = (await client.get("/api/v1/health")).json()["pool"]
        latencies: list[float] = []
        statuses: dict[int, int] = {}
        samples: list[dict] = []
        queue: asyncio.Queue[int] = asyncio.Queue()
        for i in range(args.requests):
            queue.put_nowait(i)

        async def worker():
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                t0 = time.perf_counter()
                try:
                    r = await client.get(args.path)
                    statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
                except httpx.HTTPError:
                    statuses[0] = statuses.get(0, 0) + 1
                latencies.append((time.perf_counter() - t0) * 1000)

        async def sampler():
            async with httpx.AsyncClient(base_url=args.url, verify=False, timeout=5) as probe:
                while not done.is_set():
                    try:
                        samples.append((await probe.get("/api/v1/health")).json()["pool"])
                    except Exception:
                        pass
                    await asyncio.sleep(0.25)

        done = asyncio.Event()
        sample_task = asyncio.create_task(sampler())
        t0 = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        elapsed = time.perf_counter() - t0
        done.set()
        await sample_task
        await asyncio.sleep(1)
        after = (await client.get("/api/v1/health")).json()["pool"]

    latencies.sort()
    pct = lambda p: latencies[min(len(latencies) - 1, int(len(latencies) * p))]  # noqa: E731
    print(f"Requests: {args.requests}  concurrency: {args.concurrency}  time: {elapsed:.2f}s  "
          f"throughput: {args.requests / elapsed:.0f} req/s")
    print(f"Status codes: {dict(sorted(statuses.items()))}")
    print(f"Latency ms: p50 {pct(.5):.1f}  p95 {pct(.95):.1f}  p99 {pct(.99):.1f}  max {latencies[-1]:.1f}  "
          f"mean {statistics.mean(latencies):.1f}")
    print("\nConnection pool:")
    print(f"  before : {before}")
    if samples:
        print(f"  during : peak pool_size {max(s['pool_size'] for s in samples)} / pool_max {before['pool_max']}, "
              f"peak requests_waiting {max(s['requests_waiting'] for s in samples)}")
    print(f"  after  : {after}")
    opened = after["connections_num"] - before["connections_num"]
    print(f"\n  new physical connections opened during the test: {opened} "
          f"(for {args.requests} requests → {'connections reused' if opened <= before['pool_max'] else 'CHECK FOR CHURN'})")
    leak = after["pool_available"] != after["pool_size"] or after["requests_waiting"] != 0
    print(f"  leak check: {'FAIL, connections still checked out' if leak else 'PASS, all connections returned to the pool'}")
    print("  (429 responses mean the rate limiter worked; raise RATE_LIMIT_PER_MINUTE to stress the pool itself.)")


if __name__ == "__main__":
    asyncio.run(main())
