import argparse
import asyncio
import math
import random
import statistics
import sys
import types
from dataclasses import dataclass
from time import perf_counter
from types import SimpleNamespace
from typing import Dict, List
from unittest.mock import patch

import httpx

from config import EVENT_ALPHA, VECTOR_DIM


def normalize(vector):
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def update_profile_vector(old_vec, item_vec, event_type: str):
    alpha = EVENT_ALPHA.get(event_type, 0.08)
    mixed = [((1 - alpha) * old) + (alpha * item) for old, item in zip(old_vec, item_vec)]
    return normalize(mixed)


def install_recommender_stub():
    stub = types.ModuleType("recommender")
    stub.get_item_vector = None
    stub.init_qdrant = None
    stub.search_similar_items = None
    stub.update_profile_vector = update_profile_vector
    stub.upsert_item_to_qdrant = None
    stub.get_qdrant_collection = None
    stub.list_qdrant_collections = None
    stub.qdrant_healthcheck = None
    stub.scroll_qdrant_points = None
    sys.modules.setdefault("recommender", stub)


install_recommender_stub()
import app as app_module

# 压测时不需要执行真实 startup（否则会初始化 SQLite / Qdrant）。
app_module.app.router.on_startup.clear()


@dataclass
class BenchmarkResult:
    total_requests: int
    concurrency: int
    total_time_sec: float
    throughput_rps: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    max_latency_ms: float


class FakeRecommendationBackend:
    def __init__(self, users: int, items: int, candidate_pool_size: int):
        self.user_vectors: Dict[str, List[float]] = {
            f"user_{idx:05d}": self._build_vector(idx) for idx in range(users)
        }
        self.item_vectors: Dict[int, List[float]] = {
            idx + 1: self._build_vector(idx + 10_000) for idx in range(items)
        }
        self.items = {
            item_id: {
                "item_id": item_id,
                "title": f"压测内容 {item_id}",
                "description": f"用于高并发压测的候选内容 {item_id}",
                "modality": "image_text",
                "author_id": f"author_{item_id % 1000}",
                "tags": ["benchmark", "load-test", f"bucket-{item_id % 10}"],
                "image_url": "",
                "created_at": f"2026-03-{(item_id % 28) + 1:02d} 12:00:00",
            }
            for item_id in self.item_vectors
        }
        self.candidate_pool_size = max(1, min(candidate_pool_size, items))
        self.event_count = 0
        self.update_count = 0

    @staticmethod
    def _build_vector(seed: int) -> List[float]:
        values = [math.sin(seed * 0.13 + offset * 0.017) for offset in range(VECTOR_DIM)]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    async def get_user_vector(self, user_id: str):
        return list(self.user_vectors.get(user_id, [])) or None

    async def get_item_vector(self, item_id: int):
        return self.item_vectors.get(item_id)

    async def insert_event(self, user_id: str, item_id: int, event_type: str):
        self.event_count += 1

    async def update_user_vector(self, user_id: str, vector):
        self.user_vectors[user_id] = vector
        self.update_count += 1

    async def get_latest_items(self, limit: int = 20):
        latest_ids = sorted(self.items.keys(), reverse=True)[:limit]
        return [self.items[item_id] for item_id in latest_ids]

    async def search_similar_items(self, user_vec, limit: int = 20):
        limit = min(limit, self.candidate_pool_size)
        scored = []
        for item_id in range(1, self.candidate_pool_size + 1):
            item_vec = self.item_vectors[item_id]
            score = sum(u * i for u, i in zip(user_vec, item_vec))
            scored.append((score, item_id))
        scored.sort(key=lambda row: row[0], reverse=True)

        points = []
        for score, item_id in scored[:limit]:
            payload = self.items[item_id]
            points.append(SimpleNamespace(id=item_id, score=score, payload=payload))
        return points


async def execute_single_request(client: httpx.AsyncClient, user_id: str, item_ids: List[int], events: List[str], k: int):
    payload = {
        "user_id": user_id,
        "recent_item_ids": item_ids,
        "recent_events": events,
        "k": k,
    }

    start = perf_counter()
    response = await client.post("/feed/refresh", json=payload)
    latency_ms = (perf_counter() - start) * 1000

    if response.status_code != 200:
        raise AssertionError(f"request failed: status={response.status_code}, body={response.text}")

    return latency_ms, response.json()


async def run_benchmark(args) -> BenchmarkResult:
    backend = FakeRecommendationBackend(
        users=args.users,
        items=args.items,
        candidate_pool_size=args.candidate_pool_size,
    )
    rng = random.Random(args.seed)
    user_ids = list(backend.user_vectors.keys())
    item_ids = list(backend.item_vectors.keys())
    event_types = ["view", "like", "favorite"]
    latencies = []
    semaphore = asyncio.Semaphore(args.concurrency)

    transport = httpx.ASGITransport(app=app_module.app)

    async def worker(request_index: int, client: httpx.AsyncClient):
        async with semaphore:
            user_id = user_ids[request_index % len(user_ids)]
            sampled_items = rng.sample(item_ids, k=args.events_per_request)
            sampled_events = [
                event_types[(request_index + offset) % len(event_types)]
                for offset in range(args.events_per_request)
            ]
            latency_ms, response = await execute_single_request(
                client,
                user_id,
                sampled_items,
                sampled_events,
                args.top_k,
            )
            if response.get("mode") not in {"personalized", "cold_start_latest"}:
                raise AssertionError(f"unexpected response mode: {response}")
            latencies.append(latency_ms)

    patches = [
        patch.object(app_module, "get_user_vector", backend.get_user_vector),
        patch.object(app_module, "get_item_vector", backend.get_item_vector),
        patch.object(app_module, "insert_event", backend.insert_event),
        patch.object(app_module, "update_user_vector", backend.update_user_vector),
        patch.object(app_module, "search_similar_items", backend.search_similar_items),
        patch.object(app_module, "get_latest_items", backend.get_latest_items),
    ]

    for mocked in patches:
        mocked.start()

    started_at = perf_counter()
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://benchmark.local") as client:
            await asyncio.gather(*(worker(i, client) for i in range(args.requests)))
    finally:
        for mocked in reversed(patches):
            mocked.stop()
    total_time = perf_counter() - started_at

    sorted_latencies = sorted(latencies)

    def percentile(ratio: float) -> float:
        if not sorted_latencies:
            return 0.0
        index = min(len(sorted_latencies) - 1, max(0, math.ceil(len(sorted_latencies) * ratio) - 1))
        return sorted_latencies[index]

    return BenchmarkResult(
        total_requests=args.requests,
        concurrency=args.concurrency,
        total_time_sec=total_time,
        throughput_rps=args.requests / total_time if total_time else 0.0,
        avg_latency_ms=statistics.fmean(sorted_latencies) if sorted_latencies else 0.0,
        p50_latency_ms=percentile(0.50),
        p95_latency_ms=percentile(0.95),
        p99_latency_ms=percentile(0.99),
        max_latency_ms=max(sorted_latencies) if sorted_latencies else 0.0,
    )


def format_interpretation(result: BenchmarkResult) -> List[str]:
    return [
        "",
        "--- 指标解释 ---",
        f"1) 这次一共压了 {result.total_requests} 个请求，并发度是 {result.concurrency}。",
        f"2) total_time_sec={result.total_time_sec:.3f}，表示这 {result.total_requests} 个请求总共用了 {result.total_time_sec:.3f} 秒跑完。",
        f"3) throughput_rps={result.throughput_rps:.2f}，表示系统当前大约每秒能处理 {result.throughput_rps:.2f} 个 /feed/refresh 请求。",
        f"4) avg_latency_ms={result.avg_latency_ms:.2f}，表示单个请求平均耗时约 {result.avg_latency_ms:.2f} 毫秒。",
        f"5) p50_latency_ms={result.p50_latency_ms:.2f}，表示 50% 的请求在 {result.p50_latency_ms:.2f} 毫秒内完成，也就是“典型请求耗时”。",
        f"6) p95_latency_ms={result.p95_latency_ms:.2f}，表示 95% 的请求在 {result.p95_latency_ms:.2f} 毫秒内完成，只有 5% 更慢。",
        f"7) p99_latency_ms={result.p99_latency_ms:.2f}，表示 99% 的请求在 {result.p99_latency_ms:.2f} 毫秒内完成，只有 1% 更慢。",
        f"8) max_latency_ms={result.max_latency_ms:.2f}，表示这轮压测里最慢的那个请求用了 {result.max_latency_ms:.2f} 毫秒。",
        "",
        "--- 如何判断好不好 ---",
        "- 如果你关心吞吐：重点看 throughput_rps，值越大越好。",
        "- 如果你关心用户体验：重点看 p95 / p99，值越小越好。",
        "- avg 很容易被少数慢请求掩盖，线上更建议看 p95 / p99。",
        "- 是否达标，取决于你的目标。例如目标是 100 QPS 且 P95 < 50ms，那么当前结果需要同时对照这两个门槛判断。",
    ]


def parse_args():
    parser = argparse.ArgumentParser(description="推荐系统高负载/高并发性能压测脚本（通过真实 FastAPI app 发起 HTTP 请求）")
    parser.add_argument("--requests", type=int, default=1000, help="总请求数")
    parser.add_argument("--concurrency", type=int, default=200, help="并发协程数")
    parser.add_argument("--users", type=int, default=500, help="参与压测的用户数")
    parser.add_argument("--items", type=int, default=2000, help="参与压测的内容数")
    parser.add_argument("--candidate-pool-size", type=int, default=800, help="每次召回时参与打分的候选内容数")
    parser.add_argument("--events-per-request", type=int, default=3, help="每个请求附带的行为数")
    parser.add_argument("--top-k", type=int, default=20, help="每次请求返回的推荐数量")
    parser.add_argument("--seed", type=int, default=20260320, help="随机种子，保证结果可复现")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.events_per_request <= 0:
        raise ValueError("--events-per-request 必须大于 0")
    if args.concurrency <= 0:
        raise ValueError("--concurrency 必须大于 0")
    if args.requests <= 0:
        raise ValueError("--requests 必须大于 0")
    if args.events_per_request > args.items:
        raise ValueError("--events-per-request 不能大于 --items")

    result = asyncio.run(run_benchmark(args))

    print("=== Recommendation App Load Benchmark ===")
    print(f"total_requests     : {result.total_requests}")
    print(f"concurrency        : {result.concurrency}")
    print(f"total_time_sec     : {result.total_time_sec:.3f}")
    print(f"throughput_rps     : {result.throughput_rps:.2f}")
    print(f"avg_latency_ms     : {result.avg_latency_ms:.2f}")
    print(f"p50_latency_ms     : {result.p50_latency_ms:.2f}")
    print(f"p95_latency_ms     : {result.p95_latency_ms:.2f}")
    print(f"p99_latency_ms     : {result.p99_latency_ms:.2f}")
    print(f"max_latency_ms     : {result.max_latency_ms:.2f}")
    for line in format_interpretation(result):
        print(line)


if __name__ == "__main__":
    main()
