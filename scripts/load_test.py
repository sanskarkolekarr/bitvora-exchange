"""
BITVORA EXCHANGE — Load Test Script
Simulates concurrent users hitting the API to validate performance.

Usage:
    python scripts/load_test.py --base-url http://localhost:8000 --users 100 --duration 60

Target metrics (Hetzner CX32):
    - p95 latency < 200ms for API endpoints
    - Error rate < 0.1%
    - Queue depth < 500 during peak load
"""

import asyncio
import argparse
import json
import time
import random
import string
import statistics
from dataclasses import dataclass, field
from typing import Optional

try:
    import httpx
except ImportError:
    print("Error: httpx required. Install with: pip install httpx")
    exit(1)


@dataclass
class Stats:
    """Collects latency and error statistics."""
    latencies: list[float] = field(default_factory=list)
    errors: int = 0
    total: int = 0
    status_codes: dict[int, int] = field(default_factory=dict)
    start_time: float = 0
    end_time: float = 0

    @property
    def rps(self) -> float:
        duration = self.end_time - self.start_time
        return self.total / duration if duration > 0 else 0

    @property
    def error_rate(self) -> float:
        return (self.errors / self.total * 100) if self.total > 0 else 0

    @property
    def p50(self) -> float:
        return self._percentile(50)

    @property
    def p95(self) -> float:
        return self._percentile(95)

    @property
    def p99(self) -> float:
        return self._percentile(99)

    def _percentile(self, p: int) -> float:
        if not self.latencies:
            return 0
        sorted_l = sorted(self.latencies)
        idx = int(len(sorted_l) * p / 100)
        return sorted_l[min(idx, len(sorted_l) - 1)]


def random_string(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


async def simulate_user(
    user_id: int,
    client: httpx.AsyncClient,
    base_url: str,
    stats: Stats,
    duration: float,
):
    """
    Simulate a single user session:
    1. Health check
    2. Get supported assets
    3. Get exchange rates (quote)
    4. Check transaction status
    """
    start = time.monotonic()

    while (time.monotonic() - start) < duration:
        # ─── Request 1: Health check ───
        await _request(client, "GET", f"{base_url}/health", stats)

        # ─── Request 2: Get assets ───
        await _request(client, "GET", f"{base_url}/api/assets", stats)

        # ─── Request 3: Get rates ───
        await _request(client, "GET", f"{base_url}/api/assets/rates", stats)

        # ─── Request 4: Status page data ───
        await _request(client, "GET", f"{base_url}/api/status/platform", stats)

        # Small delay between request sequences
        await asyncio.sleep(random.uniform(0.5, 2.0))


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    stats: Stats,
    json_data: Optional[dict] = None,
):
    """Make a single request and record stats."""
    try:
        start = time.monotonic()
        if method == "GET":
            resp = await client.get(url)
        elif method == "POST":
            resp = await client.post(url, json=json_data)
        else:
            return

        latency_ms = (time.monotonic() - start) * 1000

        stats.total += 1
        stats.latencies.append(latency_ms)

        code = resp.status_code
        stats.status_codes[code] = stats.status_codes.get(code, 0) + 1

        if code >= 400:
            stats.errors += 1

    except Exception as e:
        stats.total += 1
        stats.errors += 1


async def sample_health(
    client: httpx.AsyncClient,
    base_url: str,
    duration: float,
    interval: float = 5.0,
):
    """Sample /health endpoint periodically for queue depth."""
    depths = []
    start = time.monotonic()

    while (time.monotonic() - start) < duration:
        try:
            resp = await client.get(f"{base_url}/health")
            data = resp.json()
            depth = data.get("checks", {}).get("queue", {}).get("depth", "N/A")
            depths.append(depth)
        except Exception:
            pass
        await asyncio.sleep(interval)

    return depths


async def run_load_test(base_url: str, num_users: int, duration: int):
    """Run the full load test."""
    print(f"\n{'═' * 60}")
    print(f"  BITVORA EXCHANGE — Load Test")
    print(f"{'═' * 60}")
    print(f"  Target:    {base_url}")
    print(f"  Users:     {num_users} concurrent")
    print(f"  Duration:  {duration}s")
    print(f"{'═' * 60}\n")

    stats = Stats()

    limits = httpx.Limits(
        max_connections=num_users * 2,
        max_keepalive_connections=num_users,
    )
    timeout = httpx.Timeout(10.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        # Verify target is reachable
        try:
            resp = await client.get(f"{base_url}/health")
            print(f"  Target reachable: {resp.status_code}")
        except Exception as e:
            print(f"  ERROR: Cannot reach {base_url}: {e}")
            return

        stats.start_time = time.monotonic()

        # Start all user simulations + health sampler
        tasks = [
            asyncio.create_task(
                simulate_user(i, client, base_url, stats, duration)
            )
            for i in range(num_users)
        ]

        health_task = asyncio.create_task(
            sample_health(client, base_url, duration)
        )

        # Progress indicator
        progress_task = asyncio.create_task(_progress(duration, stats))

        await asyncio.gather(*tasks, return_exceptions=True)
        stats.end_time = time.monotonic()

        progress_task.cancel()
        depths = await health_task

    # ─── Report ───
    print(f"\n\n{'═' * 60}")
    print(f"  Results")
    print(f"{'═' * 60}")
    print(f"  Total requests:     {stats.total:,}")
    print(f"  Requests/sec:       {stats.rps:.1f}")
    print(f"  Error rate:         {stats.error_rate:.2f}%")
    print(f"  Errors:             {stats.errors:,}")
    print()
    print(f"  Latency (ms):")
    print(f"    p50:              {stats.p50:.1f}")
    print(f"    p95:              {stats.p95:.1f}")
    print(f"    p99:              {stats.p99:.1f}")
    if stats.latencies:
        print(f"    min:              {min(stats.latencies):.1f}")
        print(f"    max:              {max(stats.latencies):.1f}")
        print(f"    avg:              {statistics.mean(stats.latencies):.1f}")
    print()
    print(f"  Status codes:")
    for code, count in sorted(stats.status_codes.items()):
        print(f"    {code}: {count:,}")
    print()
    if depths:
        numeric_depths = [d for d in depths if isinstance(d, (int, float))]
        if numeric_depths:
            print(f"  Queue depth (sampled every 5s):")
            print(f"    min:              {min(numeric_depths)}")
            print(f"    max:              {max(numeric_depths)}")
            print(f"    avg:              {statistics.mean(numeric_depths):.1f}")
    print()

    # ─── Pass/Fail ───
    passed = True
    if stats.p95 > 200:
        print(f"  ❌ FAIL: p95 latency {stats.p95:.1f}ms > 200ms target")
        passed = False
    else:
        print(f"  ✅ PASS: p95 latency {stats.p95:.1f}ms < 200ms target")

    if stats.error_rate > 0.1:
        print(f"  ❌ FAIL: Error rate {stats.error_rate:.2f}% > 0.1% target")
        passed = False
    else:
        print(f"  ✅ PASS: Error rate {stats.error_rate:.2f}% < 0.1% target")

    print(f"\n{'═' * 60}\n")
    return passed


async def _progress(duration: float, stats: Stats):
    """Print progress every 5 seconds."""
    start = time.monotonic()
    try:
        while True:
            await asyncio.sleep(5)
            elapsed = time.monotonic() - start
            print(
                f"  [{elapsed:.0f}s/{duration}s] "
                f"requests={stats.total:,} "
                f"errors={stats.errors} "
                f"rps={stats.total / elapsed:.1f}"
            )
    except asyncio.CancelledError:
        pass


def main():
    parser = argparse.ArgumentParser(description="BITVORA Exchange Load Test")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--users",
        type=int,
        default=100,
        help="Number of concurrent users (default: 100)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Test duration in seconds (default: 60)",
    )
    args = parser.parse_args()

    asyncio.run(run_load_test(args.base_url, args.users, args.duration))


if __name__ == "__main__":
    main()
