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
    stub.upsert_items_to_qdrant_batch = None
    stub.get_qdrant_collection = None
    stub.list_qdrant_collections = None
    stub.qdrant_healthcheck = None
    stub.scroll_qdrant_points = None
    sys.modules.setdefault("recommender", stub)


install_recommender_stub()
import app as app_module


@dataclass
class BenchmarkResult:
    suite_name: str
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

    async def create_user(self, user_id: str):
        self.user_vectors.setdefault(user_id, [0.0] * VECTOR_DIM)

    async def create_users(self, user_ids: List[str]):
        for user_id in user_ids:
            await self.create_user(user_id)

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

    async def insert_item(self, item):
        self.items[item["item_id"]] = item
        self.item_vectors[item["item_id"]] = self._build_vector(item["item_id"] + 10_000)

    async def insert_items(self, items):
        for item in items:
            await self.insert_item(item)

    async def upsert_item_to_qdrant(self, item):
        await self.insert_item(item)

    async def upsert_items_to_qdrant_batch(self, items, batch_size: int = 64):
        await self.insert_items(items)

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


def build_item(item_id: int) -> dict:
    return {
        "item_id": item_id,
        "title": f"压测内容 {item_id}",
        "description": f"真实链路压测内容 {item_id}",
        "modality": "image_text",
        "author_id": f"author_{item_id % 1000}",
        "tags": ["benchmark", f"bucket-{item_id % 10}"],
        "image_url": "",
        "created_at": f"2026-03-{(item_id % 28) + 1:02d} 12:00:00",
    }


def build_bootstrap_items(item_count: int) -> List[dict]:
    return [build_item(item_id) for item_id in range(1, item_count + 1)]


async def bootstrap_fullstack_data(client: httpx.AsyncClient, user_ids: List[str], item_count: int, batch_size: int):
    users_resp = await client.post("/init/users", json={"users": user_ids})
    if users_resp.status_code != 200:
        raise AssertionError(f"bootstrap users failed: status={users_resp.status_code}, body={users_resp.text}")

    items_payload = {"items": build_bootstrap_items(item_count)}
    if batch_size > 0:
        items_payload["batch_size"] = batch_size
    items_resp = await client.post("/init/items", json=items_payload)
    if items_resp.status_code != 200:
        raise AssertionError(f"bootstrap items failed: status={items_resp.status_code}, body={items_resp.text}")


async def execute_request(client: httpx.AsyncClient, suite_name: str, payload: dict):
    endpoint_map = {
        "user": "/users",
        "item": "/items",
        "refresh": "/feed/refresh",
    }
    start = perf_counter()
    response = await client.post(endpoint_map[suite_name], json=payload)
    latency_ms = (perf_counter() - start) * 1000
    body_text = response.text
    body_json = None
    if response.status_code == 200:
        body_json = response.json()
    return latency_ms, response.status_code, body_text, body_json


@asynccontextmanager
async def isolated_client(args):
    backend = FakeRecommendationBackend(
        users=args.users,
        items=args.items,
        candidate_pool_size=args.candidate_pool_size,
    )
    app_module.app.router.on_startup.clear()
    patches = []
    for attr_name in [
        "create_user",
        "create_users",
        "get_user_vector",
        "get_item_vector",
        "insert_event",
        "update_user_vector",
        "search_similar_items",
        "get_latest_items",
        "insert_item",
        "insert_items",
        "upsert_item_to_qdrant",
        "upsert_items_to_qdrant_batch",
    ]:
        if hasattr(app_module, attr_name):
            patches.append(patch.object(app_module, attr_name, getattr(backend, attr_name)))
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


def build_payload(suite_name: str, request_index: int, rng: random.Random, args, user_ids, item_ids):
    if suite_name == "user":
        return {"user_id": f"bench_user_create_{request_index:06d}"}
    if suite_name == "item":
        return build_item(args.items + request_index + 1)
    sampled_items = rng.sample(item_ids, k=args.events_per_request)
    sampled_events = [
        ["view", "like", "favorite"][(request_index + offset) % 3]
        for offset in range(args.events_per_request)
    ]
    return {
        "user_id": user_ids[request_index % len(user_ids)],
        "recent_item_ids": sampled_items,
        "recent_events": sampled_events,
        "k": args.top_k,
    }


def is_success(suite_name: str, body_json: dict) -> bool:
    if suite_name == "refresh":
        return body_json.get("mode") in {"personalized", "cold_start_latest"}
    return True


async def run_suite(client: httpx.AsyncClient, suite_name: str, args, rng: random.Random, user_ids, item_ids) -> BenchmarkResult:
    latencies = []
    error_samples = []
    failed_requests = 0
    semaphore = asyncio.Semaphore(args.concurrency)

    async def worker(request_index: int):
        nonlocal failed_requests
        async with semaphore:
            payload = build_payload(suite_name, request_index, rng, args, user_ids, item_ids)
            for attempt in range(args.retries + 1):
                latency_ms, status_code, body_text, body_json = await execute_request(client, suite_name, payload)
                if status_code == 200 and body_json is not None and is_success(suite_name, body_json):
                    latencies.append(latency_ms)
                    return

                retryable = status_code in args.retry_statuses and attempt < args.retries
                if retryable:
                    continue

                failed_requests += 1
                if len(error_samples) < args.max_error_samples:
                    error_samples.append(
                        f"suite={suite_name}, status={status_code}, body={body_text[:200]!r}, attempt={attempt + 1}"
                    )
                return

    started_at = perf_counter()
    await asyncio.gather(*(worker(i) for i in range(args.requests)))
    total_time = perf_counter() - started_at
    sorted_latencies = sorted(latencies)

    def percentile(ratio: float) -> float:
        if not sorted_latencies:
            return 0.0
        index = min(len(sorted_latencies) - 1, max(0, math.ceil(len(sorted_latencies) * ratio) - 1))
        return sorted_latencies[index]

    return BenchmarkResult(
        suite_name=suite_name,
        total_requests=args.requests,
        success_requests=len(latencies),
        failed_requests=failed_requests,
        concurrency=args.concurrency,
        total_time_sec=total_time,
        throughput_rps=args.requests / total_time if total_time else 0.0,
        avg_latency_ms=statistics.fmean(sorted_latencies) if sorted_latencies else 0.0,
        p50_latency_ms=percentile(0.50),
        p95_latency_ms=percentile(0.95),
        p99_latency_ms=percentile(0.99),
        max_latency_ms=max(sorted_latencies) if sorted_latencies else 0.0,
        error_samples=error_samples,
    )


async def run_benchmark(args) -> List[BenchmarkResult]:
    rng = random.Random(args.seed)
    user_ids = [f"user_{idx:05d}" for idx in range(args.users)]
    item_ids = list(range(1, args.items + 1))

    if args.mode == "fullstack":
        client_factory = fullstack_client
    else:
        client_factory = isolated_client

    async with client_factory(args) as client:
        if args.mode == "fullstack" and args.bootstrap_data:
            await bootstrap_fullstack_data(client, user_ids, args.items, args.item_batch_size)
        results = []
        for suite_name in args.suites:
            results.append(await run_suite(client, suite_name, args, rng, user_ids, item_ids))
        return results


def parse_args():
    parser = argparse.ArgumentParser(description="推荐系统高负载/高并发性能压测脚本")
    parser.add_argument("--mode", choices=["isolated", "fullstack"], default="fullstack")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--bootstrap-data", action="store_true")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--suites", nargs="+", choices=["user", "item", "refresh"], default=["user", "item", "refresh"], help="依次运行的压测场景")
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--users", type=int, default=500)
    parser.add_argument("--items", type=int, default=2000)
    parser.add_argument("--candidate-pool-size", type=int, default=800)
    parser.add_argument("--events-per-request", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--item-batch-size", type=int, default=64, help="bootstrap /init/items 时传入的 batch_size")
    parser.add_argument("--seed", type=int, default=20260320)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-statuses", type=int, nargs="+", default=[502, 503, 504])
    parser.add_argument("--max-error-samples", type=int, default=5)
    return parser.parse_args()


def print_result(result: BenchmarkResult):
    print(f"=== {result.suite_name.upper()} Benchmark ===")
    print(f"suite              : {result.suite_name}")
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
    if result.error_samples:
        print("error_samples      :")
        for sample in result.error_samples:
            print(f"  - {sample}")
    print()


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

    results = asyncio.run(run_benchmark(args))
    print("=== Recommendation App Load Benchmark Suite ===")
    print(f"mode               : {args.mode}")
    print(f"suites             : {', '.join(args.suites)}")
    print(f"requests           : {args.requests}")
    print(f"concurrency        : {args.concurrency}")
    print()
    for result in results:
        print_result(result)


if __name__ == "__main__":
    main()
