import argparse
import asyncio
import math
import random
import statistics
import sys
import types
import warnings
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import perf_counter
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional
from unittest.mock import patch

import httpx

from config import EVENT_ALPHA, VECTOR_DIM

import os

print("HTTP_PROXY =", os.getenv("HTTP_PROXY"))
print("HTTPS_PROXY =", os.getenv("HTTPS_PROXY"))
print("ALL_PROXY =", os.getenv("ALL_PROXY"))
print("NO_PROXY =", os.getenv("NO_PROXY"))


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
    stub.upsert_items_to_qdrant = None
    stub.get_qdrant_collection = None
    stub.list_qdrant_collections = None
    stub.qdrant_healthcheck = None
    stub.scroll_qdrant_points = None
    sys.modules.setdefault("recommender", stub)


install_recommender_stub()
import app as app_module


@dataclass
class BenchmarkResult:
    phase: str
    mode: str
    total_requests: int
    success_requests: int
    failed_requests: int
    concurrency: int
    total_time_sec: float
    throughput_rps: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    max_latency_ms: float
    error_samples: List[str]


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
        return None

    async def update_user_vector(self, user_id: str, vector):
        self.user_vectors[user_id] = vector

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
        return [
            SimpleNamespace(id=item_id, score=score, payload=self.items[item_id])
            for score, item_id in scored[:limit]
        ]


@asynccontextmanager
async def isolated_client(args):
    backend = FakeRecommendationBackend(
        users=args.users,
        items=args.items,
        candidate_pool_size=args.candidate_pool_size,
    )
    app_module.app.router.on_startup.clear()
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

    transport = httpx.ASGITransport(app=app_module.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://benchmark.local") as client:
            yield client
    finally:
        for mocked in reversed(patches):
            mocked.stop()


async def maybe_check_readyz(client: httpx.AsyncClient):
    try:
        ready = await client.get("/readyz")
    except Exception as exc:
        warnings.warn(f"/readyz check failed and will be skipped: {exc}")
        return

    if ready.status_code != 200:
        warnings.warn(
            f"/readyz returned status={ready.status_code}, body={ready.text!r}; benchmark will continue"
        )


@asynccontextmanager
async def fullstack_client(args):
    async with httpx.AsyncClient(
        base_url=args.base_url,
        timeout=args.timeout_sec,
        trust_env=False,
    ) as client:
        await maybe_check_readyz(client)
        yield client


def build_bootstrap_items(item_count: int) -> List[dict]:
    return [
        {
            "item_id": item_id,
            "title": f"压测内容 {item_id}",
            "description": f"真实链路压测内容 {item_id}",
            "modality": "image_text",
            "author_id": f"author_{item_id % 1000}",
            "tags": ["benchmark", f"bucket-{item_id % 10}"],
            "image_url": "",
            "created_at": f"2026-03-{(item_id % 28) + 1:02d} 12:00:00",
        }
        for item_id in range(1, item_count + 1)
    ]


def make_percentile(sorted_latencies: List[float], ratio: float) -> float:
    if not sorted_latencies:
        return 0.0
    index = min(len(sorted_latencies) - 1, max(0, math.ceil(len(sorted_latencies) * ratio) - 1))
    return sorted_latencies[index]


async def benchmark_phase(
    *,
    args,
    client: httpx.AsyncClient,
    phase: str,
    total_requests: int,
    request_factory: Callable[[int], tuple[str, dict]],
    validator: Optional[Callable[[httpx.Response], Optional[str]]] = None,
) -> BenchmarkResult:
    latencies: List[float] = []
    error_samples: List[str] = []
    failed_requests = 0
    semaphore = asyncio.Semaphore(args.concurrency)

    async def worker(request_index: int):
        nonlocal failed_requests
        async with semaphore:
            method, payload = request_factory(request_index)
            for attempt in range(args.retries + 1):
                start = perf_counter()
                if method == "POST":
                    response = await client.post(payload["path"], json=payload["json"])
                else:
                    raise ValueError(f"unsupported method: {method}")
                latency_ms = (perf_counter() - start) * 1000

                validation_error = validator(response) if validator else None
                if response.status_code == 200 and validation_error is None:
                    latencies.append(latency_ms)
                    return

                retryable = response.status_code in args.retry_statuses and attempt < args.retries
                if retryable:
                    continue

                failed_requests += 1
                if len(error_samples) < args.max_error_samples:
                    detail = validation_error or response.text[:200]
                    error_samples.append(
                        f"phase={phase}, status={response.status_code}, detail={detail!r}, attempt={attempt + 1}"
                    )
                return

    started_at = perf_counter()
    await asyncio.gather(*(worker(i) for i in range(total_requests)))
    total_time = perf_counter() - started_at
    sorted_latencies = sorted(latencies)

    return BenchmarkResult(
        phase=phase,
        mode=args.mode,
        total_requests=total_requests,
        success_requests=len(latencies),
        failed_requests=failed_requests,
        concurrency=args.concurrency,
        total_time_sec=total_time,
        throughput_rps=total_requests / total_time if total_time else 0.0,
        avg_latency_ms=statistics.fmean(sorted_latencies) if sorted_latencies else 0.0,
        p50_latency_ms=make_percentile(sorted_latencies, 0.50),
        p95_latency_ms=make_percentile(sorted_latencies, 0.95),
        p99_latency_ms=make_percentile(sorted_latencies, 0.99),
        max_latency_ms=max(sorted_latencies) if sorted_latencies else 0.0,
        error_samples=error_samples,
    )


async def run_benchmark(args) -> List[BenchmarkResult]:
    rng = random.Random(args.seed)
    user_ids = [f"user_{idx:05d}" for idx in range(args.users)]
    item_ids = list(range(1, args.items + 1))
    event_types = ["view", "like", "favorite"]

    client_factory = fullstack_client if args.mode == "fullstack" else isolated_client
    results: List[BenchmarkResult] = []

    async with client_factory(args) as client:
        if args.mode == "fullstack":
            if args.benchmark_users:
                results.append(
                    await benchmark_phase(
                        args=args,
                        client=client,
                        phase="users",
                        total_requests=args.user_batches,
                        request_factory=lambda request_index: (
                            "POST",
                            {
                                "path": "/init/users",
                                "json": {
                                    "users": [
                                        f"bench_user_{request_index:04d}_{offset:04d}"
                                        for offset in range(args.users_per_batch)
                                    ]
                                },
                            },
                        ),
                    )
                )

            if args.benchmark_items:
                results.append(
                    await benchmark_phase(
                        args=args,
                        client=client,
                        phase="items",
                        total_requests=args.item_batches,
                        request_factory=lambda request_index: (
                            "POST",
                            {
                                "path": "/init/items",
                                "json": {
                                    "items": [
                                        {
                                            "item_id": (request_index * args.items_per_batch) + offset + 1,
                                            "title": f"批量内容 {(request_index * args.items_per_batch) + offset + 1}",
                                            "description": f"压测批次 {request_index}",
                                            "modality": "image_text",
                                            "author_id": f"author_{offset % 1000}",
                                            "tags": ["benchmark", f"batch-{request_index}"],
                                            "image_url": "",
                                            "created_at": f"2026-03-{(offset % 28) + 1:02d} 12:00:00",
                                        }
                                        for offset in range(args.items_per_batch)
                                    ],
                                    "vector_batch_size": args.vector_batch_size,
                                },
                            },
                        ),
                    )
                )

            if args.bootstrap_data:
                users_resp = await client.post("/init/users", json={"users": user_ids})
                if users_resp.status_code != 200:
                    raise AssertionError(
                        f"bootstrap users failed: status={users_resp.status_code}, body={users_resp.text}"
                    )
                items_resp = await client.post(
                    "/init/items",
                    json={"items": build_bootstrap_items(args.items), "vector_batch_size": args.vector_batch_size},
                )
                if items_resp.status_code != 200:
                    raise AssertionError(
                        f"bootstrap items failed: status={items_resp.status_code}, body={items_resp.text}"
                    )

        results.append(
            await benchmark_phase(
                args=args,
                client=client,
                phase="refresh",
                total_requests=args.requests,
                request_factory=lambda request_index: (
                    "POST",
                    {
                        "path": "/feed/refresh",
                        "json": {
                            "user_id": user_ids[request_index % len(user_ids)],
                            "recent_item_ids": rng.sample(item_ids, k=args.events_per_request),
                            "recent_events": [
                                event_types[(request_index + offset) % len(event_types)]
                                for offset in range(args.events_per_request)
                            ],
                            "k": args.top_k,
                        },
                    },
                ),
                validator=lambda response: None
                if response.json().get("mode") in {"personalized", "cold_start_latest"}
                else f"unexpected response mode: {response.text[:200]}"
                if response.status_code == 200
                else None,
            )
        )

    return results


def format_interpretation(result: BenchmarkResult) -> List[str]:
    mode_name = "真实全链路模式" if result.mode == "fullstack" else "隔离依赖模式"
    phase_name = {"users": "用户初始化", "items": "内容初始化", "refresh": "刷新推荐"}.get(result.phase, result.phase)
    return [
        "",
        f"--- 指标解释（{mode_name} / {phase_name}） ---",
        f"1) 这次一共压了 {result.total_requests} 个请求，并发度是 {result.concurrency}。成功 {result.success_requests} 个，失败 {result.failed_requests} 个。",
        f"2) total_time_sec={result.total_time_sec:.3f}，表示这 {result.total_requests} 个请求总共用了 {result.total_time_sec:.3f} 秒跑完。",
        f"3) throughput_rps={result.throughput_rps:.2f}，表示系统当前大约每秒能处理 {result.throughput_rps:.2f} 个 {result.phase} 请求。",
        f"4) avg_latency_ms={result.avg_latency_ms:.2f}，表示单个请求平均耗时约 {result.avg_latency_ms:.2f} 毫秒。",
        f"5) p50_latency_ms={result.p50_latency_ms:.2f}，表示 50% 的请求在 {result.p50_latency_ms:.2f} 毫秒内完成。",
        f"6) p95_latency_ms={result.p95_latency_ms:.2f}，表示 95% 的请求在 {result.p95_latency_ms:.2f} 毫秒内完成。",
        f"7) p99_latency_ms={result.p99_latency_ms:.2f}，表示 99% 的请求在 {result.p99_latency_ms:.2f} 毫秒内完成。",
        f"8) max_latency_ms={result.max_latency_ms:.2f}，表示这轮压测里最慢的那个请求用了 {result.max_latency_ms:.2f} 毫秒。",
    ] + (["", "--- 失败样例 ---"] + result.error_samples if result.error_samples else [])


def parse_args():
    parser = argparse.ArgumentParser(description="推荐系统高负载/高并发性能压测脚本")
    parser.add_argument("--mode", choices=["isolated", "fullstack"], default="fullstack", help="isolated 为隔离依赖压测，fullstack 为真实依赖全链路压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="fullstack 模式下真实服务地址")
    parser.add_argument("--bootstrap-data", action="store_true", help="refresh 压测前通过 /init/users 和 /init/items 初始化压测数据")
    parser.add_argument("--timeout-sec", type=float, default=120.0, help="fullstack 模式下单请求超时秒数")
    parser.add_argument("--requests", type=int, default=1000, help="refresh 阶段总请求数")
    parser.add_argument("--concurrency", type=int, default=200, help="并发协程数")
    parser.add_argument("--users", type=int, default=500, help="refresh 阶段参与压测的用户数")
    parser.add_argument("--items", type=int, default=2000, help="refresh 阶段参与压测的内容数")
    parser.add_argument("--candidate-pool-size", type=int, default=800, help="isolated 模式下每次召回参与打分的候选内容数")
    parser.add_argument("--events-per-request", type=int, default=3, help="每个 refresh 请求附带的行为数")
    parser.add_argument("--top-k", type=int, default=20, help="每次 refresh 请求返回的推荐数量")
    parser.add_argument("--seed", type=int, default=20260320, help="随机种子，保证结果可复现")
    parser.add_argument("--retries", type=int, default=2, help="单请求在可重试状态码下的最大重试次数")
    parser.add_argument("--retry-statuses", type=int, nargs="+", default=[502, 503, 504], help="遇到这些状态码时进行重试")
    parser.add_argument("--max-error-samples", type=int, default=5, help="最终输出中最多展示多少条失败样例")
    parser.add_argument("--benchmark-users", action="store_true", help="额外展示 /init/users 阶段结果（仅 fullstack）")
    parser.add_argument("--benchmark-items", action="store_true", help="额外展示 /init/items 阶段结果（仅 fullstack）")
    parser.add_argument("--user-batches", type=int, default=10, help="用户初始化阶段的请求数")
    parser.add_argument("--users-per-batch", type=int, default=100, help="每个用户初始化请求包含的用户数量")
    parser.add_argument("--item-batches", type=int, default=10, help="内容初始化阶段的请求数")
    parser.add_argument("--items-per-batch", type=int, default=100, help="每个内容初始化请求包含的内容数量")
    parser.add_argument("--vector-batch-size", type=int, default=64, help="/init/items 调用时每批向量化并写入 Qdrant 的数量")
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
    if args.vector_batch_size <= 0:
        raise ValueError("--vector-batch-size 必须大于 0")

    results = asyncio.run(run_benchmark(args))

    print("=== Recommendation App Load Benchmark ===")
    for result in results:
        print(f"\n=== Phase: {result.phase} ===")
        print(f"mode               : {result.mode}")
        print(f"total_requests     : {result.total_requests}")
        print(f"success_requests   : {result.success_requests}")
        print(f"failed_requests    : {result.failed_requests}")
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
