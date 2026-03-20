# xzds-recommendation-algorithm

![Recommendation System](figs/intro.png)

## 0. 文档导航

- 完整接口文档：[`docs/api-reference.md`](docs/api-reference.md)
- 如果你需要查看**所有接口、所有请求字段、所有可接受配置项（含 V1/V2 差异、环境变量、行为权重、批量参数）**，请直接阅读上面的完整文档。

---

这是一个面向业务展示与交付的推荐系统项目，目标聚焦在三件事：

- **个性化推荐**：能够基于用户近期行为持续调整推荐结果，让不同用户看到更贴合兴趣的内容。
- **多模态内容承载**：支持图文等多种内容形态的统一接入、管理与推荐返回，便于后续业务扩展。
- **实时性体验**：在用户发生浏览、点赞、收藏等行为后，推荐流可以快速刷新，满足实时反馈需求。

当前项目用于演示完整推荐链路，包括：

- 用户画像初始化与动态更新
- 内容入库、特征索引与召回
- 基于用户行为的实时推荐刷新
- 冷启动场景下的兜底策略
- 线上联调和排查所需的调试接口

---

## 1. 项目介绍

本项目核心思路：

1. **内容侧建模**：将每条内容（title / description / tags）转换为文本向量，并写入 Qdrant。
2. **用户侧建模**：每个用户维护一个 384 维画像向量（SQLite 保存）。
3. **行为驱动更新**：用户发生 `view / like / favorite` 行为时，使用不同权重更新用户向量。
4. **召回推荐**：用用户向量到 Qdrant 做相似检索，返回 Top-K 内容。
5. **冷启动兜底**：当用户画像仍接近零向量时，返回按 `created_at` 倒序的最新内容。

目前仓库包含两个可运行目录：

- `xzds_rec_v1/`：已跑通的正式版本 V1。
- `xzds_rec_v2/`：正在测试中的正式版本 V2，并行化方向上额外尝试了 refresh 串行化保护、SQLite WAL/busy_timeout 调优，以及 item 分批次向量化入库。

当前默认启动配置以正式版 V1 为准（见 `xzds_rec_v1/config.py`）：

- 向量维度：`384`
- Qdrant 地址：`http://localhost:6333`
- 集合名：`items_xzds_rec_v1`
- 默认推荐数量：`20`

---

## 2. 运行与使用

## 2.1 环境准备

- Python 3.10+
- 本地或容器中的 Qdrant（默认 `6333` 端口）

安装依赖：

```bash
cd xzds_rec_v1
pip install -r requirements.txt
```

## 2.2 Qdrant 启动方式（二选一）

项目现在默认会使用本地 `qdrant_data/` 目录作为嵌入式 Qdrant 存储，因此**不启动 Docker 也能直接跑起来**。如果你希望接外部 Qdrant 服务，再使用 Docker 或你自己的 Qdrant 实例即可。

**方式 A：直接使用默认本地存储（推荐做开发调试）**

```bash
# 不需要额外启动 Qdrant
```

**方式 B：使用 Docker 启动独立 Qdrant 服务**

```bash
docker run -p 6333:6333 qdrant/qdrant
```

如果采用方式 B，请在启动应用前设置：

```bash
# Linux / macOS
export QDRANT_URL=http://127.0.0.1:6333

# Windows PowerShell
$env:QDRANT_URL="http://127.0.0.1:6333"
```

## 2.3 启动服务

在仓库根目录执行下面这条命令即可：

```bash
uvicorn xzds_rec_v1.app:app --host 0.0.0.0 --port 8000 --reload
```

> 如果你是直接运行单文件脚本（例如 `python xzds_rec_v1/perf_test_high_load.py`），项目也兼容。

启动时会自动执行：

- SQLite 表初始化
- Qdrant 集合初始化

## 2.4 查看交互式 API 文档

服务启动后可访问：

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## 2.5 安装轻量文本向量模型

默认优先按下面的顺序找模型：1）环境变量 `EMBEDDING_MODEL_NAME` 指定的路径或模型名；2）项目内的 `xzds_rec_v1/all-MiniLM-L6-v2` 本地目录；3）最后才回退到 Hugging Face 上的 `sentence-transformers/all-MiniLM-L6-v2`。如果解析到的是本地目录，代码会自动开启 `local_files_only=True`，不再请求 Hugging Face。若你想强制离线，也可以额外设置 `EMBEDDING_LOCAL_FILES_ONLY=1`。

---

## 3. 数据模型

### 3.1 UserInitRequest

```json
{
  "users": ["user_001", "user_002"]
}
```

### 3.2 ItemData

```json
{
  "item_id": 1001,
  "title": "内容标题",
  "description": "内容描述",
  "modality": "image_text",
  "author_id": "author_01",
  "tags": ["标签A", "标签B"],
  "image_url": "https://example.com/a.jpg",
  "created_at": "2026-03-15 12:00:00"
}
```

### 3.3 ItemInitRequest

```json
{
  "items": [
    {
      "item_id": 1001,
      "title": "内容标题",
      "description": "内容描述",
      "modality": "image_text",
      "author_id": "author_01",
      "tags": ["标签A"],
      "image_url": "https://example.com/a.jpg",
      "created_at": "2026-03-15 12:00:00"
    }
  ]
}
```

### 3.4 CreateUserRequest

```json
{
  "user_id": "user_001"
}
```

### 3.5 EventRequest

```json
{
  "user_id": "user_001",
  "recent_item_ids": [1001, 1002],
  "recent_events": ["view", "like"],
  "k": 20
}
```

### 3.6 QdrantScrollRequest

```json
{
  "limit": 10,
  "with_payload": true,
  "with_vector": false
}
```

---

## 4. 接口快速示例（完整版本见 [`docs/api-reference.md`](docs/api-reference.md)）

Base URL：`http://127.0.0.1:8000`

### 4.1 `POST /init/users`

批量初始化用户（仅首次创建，已存在用户不会重复插入）。

**请求体**：`UserInitRequest`

**示例**：

```bash
curl -X POST 'http://127.0.0.1:8000/init/users' \
  -H 'Content-Type: application/json' \
  -d '{"users":["user_001","user_002"]}'
```

**响应示例**：

```json
{
  "message": "users initialized",
  "count": 2
}
```

---

### 4.2 `POST /init/items`

批量初始化内容：

- 写入 SQLite `items` 表
- 写入 Qdrant 向量索引

**请求体**：`ItemInitRequest`

**示例**：

```bash
curl -X POST 'http://127.0.0.1:8000/init/items' \
  -H 'Content-Type: application/json' \
  -d '{
    "items": [
      {
        "item_id": 1001,
        "title": "春天来了",
        "description": "测试图文内容",
        "modality": "image_text",
        "author_id": "author_01",
        "tags": ["春天", "测试"],
        "image_url": "https://images.unsplash.com/photo-1503023345310-bd7c1de61c7d",
        "created_at": "2026-03-15 12:00:00"
      }
    ]
  }'

  curl -X POST "http://localhost:8000/init/users" -H "Content-Type: application/json" --data-binary @xzds_rec_v1/data/users_batch.json
curl -X POST "http://localhost:8000/init/items" -H "Content-Type: application/json" --data-binary @xzds_rec_v1/data/items_batch.json
```

**响应示例**：

```json
{
  "message": "items initialized",
  "count": 1
}
```

---

### 4.3 `POST /users`

创建单个用户。

**请求体**：`CreateUserRequest`

**示例**：

```bash
curl -X POST 'http://127.0.0.1:8000/users' \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user_003"}'
```

**响应示例**：

```json
{
  "message": "user created",
  "user_id": "user_003"
}
```

---

### 4.4 `POST /items`

创建单条内容，并同步写入 Qdrant。

**请求体**：`ItemData`

**示例**：

```bash
curl -X POST 'http://127.0.0.1:8000/items' \
  -H 'Content-Type: application/json' \
  -d '{
    "item_id": 1002,
    "title": "夏日海边",
    "description": "海边风景图文",
    "modality": "image_text",
    "author_id": "author_02",
    "tags": ["夏天", "海边"],
    "image_url": "https://example.com/beach.jpg",
    "created_at": "2026-03-16 10:00:00"
  }'
```

**响应示例**：

```json
{
  "message": "item created",
  "item_id": 1002
}
```

---

### 4.5 `POST /feed/refresh`

刷新推荐流（核心接口）：

1. 校验用户存在
2. 校验 `recent_item_ids` 与 `recent_events` 长度一致
3. 根据行为更新用户画像向量
4. 若用户向量近似零向量，则返回最新内容（冷启动）
5. 否则按向量相似度返回个性化结果

**请求体**：`EventRequest`

**示例**：

```bash
curl -X POST 'http://127.0.0.1:8000/feed/refresh' \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id":"user_001",
    "recent_item_ids":[2001,2002],
    "recent_events":["view","favorite"],
    "k":10
  }'
```

**个性化响应示例**：

```json
{
  "user_id": "user_001",
  "mode": "personalized",
  "items": [
    {
      "item_id": 1002,
      "score": 0.92,
      "title": "夏日海边",
      "description": "海边风景图文",
      "modality": "image_text",
      "author_id": "author_02",
      "tags": ["夏天", "海边"],
      "image_url": "https://example.com/beach.jpg",
      "created_at": "2026-03-16 10:00:00"
    }
  ]
}
```

**冷启动响应示例**：

```json
{
  "user_id": "user_001",
  "mode": "cold_start_latest",
  "items": [
    {
      "item_id": 1001,
      "title": "春天来了",
      "description": "测试图文内容",
      "modality": "image_text",
      "author_id": "author_01",
      "tags": ["春天", "测试"],
      "image_url": "https://images.unsplash.com/photo-1503023345310-bd7c1de61c7d",
      "created_at": "2026-03-15 12:00:00"
    }
  ]
}
```

**典型错误**：

- `404 user not found`
- `400 recent_item_ids and recent_events length mismatch`

---

### 4.6 `GET /readyz`

服务就绪检查（含 Qdrant 连通性）。

**示例**：

```bash
curl "http://127.0.0.1:8000/readyz"
```

**响应示例**：

```json
{
  "status": "ok",
  "qdrant": {
    "ok": true,
    "error": ""
  }
}
```

---

### 4.7 `GET /qdrant/collections`

返回 Qdrant 中的所有集合名。

**示例**：

```bash
curl "http://127.0.0.1:8000/qdrant/collections"
```

**响应示例**：

```json
{
  "collections": ["items_xzds_rec_v1"]
}
```

---

### 4.8 `GET /qdrant/collections/{collection_name}`

返回指定集合详情（向量配置、点数量等）。

**示例**：

```bash
curl "http://127.0.0.1:8000/qdrant/collections/items_xzds_rec_v1"
```

---

### 4.9 `POST /qdrant/collections/{collection_name}/points/scroll`

分页查看集合中的点（调试/排查用）。

**请求体**：`QdrantScrollRequest`

**示例**：

```bash
curl -X POST "http://127.0.0.1:8000/qdrant/collections/items_xzds_rec_v1/points/scroll" -H "Content-Type: application/json" -d "{\"limit\":5,\"with_payload\":true,\"with_vector\":false}"
```

**响应示例**：

```json
{
  "points": [
    {
      "id": 1001,
      "payload": {
        "title": "春天来了",
        "description": "测试图文内容",
        "modality": "image_text",
        "author_id": "author_01",
        "tags": ["春天", "测试"],
        "image_url": "https://images.unsplash.com/photo-1503023345310-bd7c1de61c7d",
        "created_at": "2026-03-15 12:00:00"
      },
      "vector": null
    }
  ],
  "next_page_offset": 1001
}
```

---

## 5. 快速初始化数据（可选）

项目附带脚本：`xzds_rec_v1/test_data_ingest.py`，可用于验证 SQLite 入库。

```bash
python xzds_rec_v1/test_data_ingest.py
```

输出出现 `[PASS]` 表示用户与内容均写入成功。

---

## 6. 注意事项

- `image_url` 可为空；系统当前仅使用标题、描述、标签做纯文本向量化；`image_url` 字段仅保留做业务透传，不参与 embedding。
- `created_at` 建议使用可排序字符串格式（如 `YYYY-MM-DD HH:MM:SS`），以保证冷启动最新内容排序正确。
- 行为权重默认：
  - `view`: 0.08
  - `like`: 0.15
  - `favorite`: 0.25
- 若要调整推荐数量、Qdrant 地址、集合名、模型名，可修改 `xzds_rec_v1/config.py`。

---

## 7. 性能测试结果说明

### 7.0 压测脚本说明

仓库额外提供了一个纯 Python 压测脚本 `xzds_rec_v1/perf_test_high_load.py`，支持两种模式：

- `--mode isolated`：隔离 Qdrant、SQLite、向量模型，只测试 FastAPI 应用层和推荐接口逻辑，适合快速定位代码层瓶颈。
- `--mode fullstack`：连接真实运行中的推荐服务，能够把 **向量化、入库、Qdrant 检索** 等真实依赖全部纳入延迟统计，更接近线上真实表现。

示例：

```bash
# 快速看应用层开销
python xzds_rec_v1/perf_test_high_load.py --mode isolated --requests 2000 --concurrency 300 --users 1000 --items 5000

# 测真实全链路延迟（需要先启动服务，并准备好 SQLite / Qdrant / 向量模型）
python xzds_rec_v1/perf_test_high_load.py --mode fullstack --base-url http://127.0.0.1:8000 --bootstrap-data --requests 200 --concurrency 5 --users 100 --items 100
```

脚本会输出总耗时、吞吐量（RPS）以及平均 / P50 / P95 / P99 延迟，便于快速评估推荐刷新链路在高负载场景下的表现。若要评估真实线上延迟，应优先使用 `fullstack` 模式。脚本对 `502/503/504` 默认会自动重试，并在最终结果中汇总失败请求数量与失败样例，而不是在第一次网关错误时直接退出。

### 7.1 实际压测结果

以下为小压力实际结果：

```text
=== 推荐系统压测总览 ===
压测模式           : fullstack
压测场景           : user, item, refresh
每场景请求数       : 200
并发度             : 5
用户数             : 100
内容数             : 100
每次 refresh 行为数: 3
item 分批大小      : 64

--- 总体分析 ---
1）本脚本会把 user、item、refresh 三类请求拆开压测，避免结果互相掩盖。
2）如果 user 很快、item 很慢，优先关注向量化和向量索引写入链路。
3）如果 item 很快、refresh 很慢，优先关注画像更新、事件落库和向量检索链路。
4）建议重点同时观察 avg / P95 / P99，而不只是平均值，因为并发问题通常先体现在尾延迟。
5）当前是 fullstack 模式：结果会覆盖真实 SQLite / 向量化 / Qdrant 链路，更接近线上瓶颈。
6）本轮吞吐最高的场景是：用户创建（89.67 req/s）。
7）本轮高位延迟最大的场景是：推荐刷新（P95=100.84 ms）。

=== 用户创建压测结果 ===
压测场景           : 用户创建
total_requests     : 200
success_requests   : 200
failed_requests    : 0
concurrency        : 5
total_time_sec     : 2.231
throughput_rps     : 89.67
avg_latency_ms     : 54.49
p50_latency_ms     : 55.25
p95_latency_ms     : 60.41
p99_latency_ms     : 61.90
max_latency_ms     : 67.26

--- 用户创建压测说明 ---
这个场景主要看批量或高并发建用户时，接口层、SQLite 写入和唯一键处理的开销。
1）本轮共发起 200 个请求，并发度为 5；成功 200 个，失败 0 个，成功率约 100.00% 。
2）总耗时 total_time_sec=2.231 秒，表示这一轮 用户创建 请求整体跑完花了 2.231 秒。
3）吞吐 throughput_rps=89.67，表示当前系统大约每秒能处理 89.67 个用户创建请求。
4）平均延迟 avg_latency_ms=54.49 ms，表示单个用户创建请求平均耗时约 54.49 毫秒。
5）P50 延迟=55.25 ms，可理解为“典型请求耗时”；一半请求会快于这个值。
6）P95 延迟=60.41 ms，用来看高位延迟是否稳定；如果它明显高于平均值，说明高并发下已有慢请求出现。
7）P99 延迟=61.90 ms，表示极少数最慢请求的水平；它越高，越说明尾部波动越明显。
8）最大延迟 max_latency_ms=67.26 ms，表示本轮最慢的那个请求耗时。
9）本轮没有失败请求，说明在当前参数下接口功能和基本稳定性是正常的。
10）从平均值与 P95 的差距看，整体延迟分布相对集中，说明抖动还比较可控。
11）如果 user 场景吞吐偏低，通常优先检查 SQLite 写入频率、事务边界和唯一索引冲突处理。

=== 内容入库压测结果 ===
压测场景           : 内容入库
total_requests     : 200
success_requests   : 200
failed_requests    : 0
concurrency        : 5
total_time_sec     : 2.437
throughput_rps     : 82.07
avg_latency_ms     : 60.07
p50_latency_ms     : 50.94
p95_latency_ms     : 91.96
p99_latency_ms     : 120.06
max_latency_ms     : 132.73

--- 内容入库压测说明 ---
这个场景主要看内容写库、向量化与向量索引写入链路的吞吐和尾延迟表现。
1）本轮共发起 200 个请求，并发度为 5；成功 200 个，失败 0 个，成功率约 100.00% 。
2）总耗时 total_time_sec=2.437 秒，表示这一轮 内容入库 请求整体跑完花了 2.437 秒。
3）吞吐 throughput_rps=82.07，表示当前系统大约每秒能处理 82.07 个内容入库请求。
4）平均延迟 avg_latency_ms=60.07 ms，表示单个内容入库请求平均耗时约 60.07 毫秒。
5）P50 延迟=50.94 ms，可理解为“典型请求耗时”；一半请求会快于这个值。
6）P95 延迟=91.96 ms，用来看高位延迟是否稳定；如果它明显高于平均值，说明高并发下已有慢请求出现。
7）P99 延迟=120.06 ms，表示极少数最慢请求的水平；它越高，越说明尾部波动越明显。
8）最大延迟 max_latency_ms=132.73 ms，表示本轮最慢的那个请求耗时。
9）本轮没有失败请求，说明在当前参数下接口功能和基本稳定性是正常的。
10）P95 明显高于平均延迟，说明已经出现较明显的尾部放大，需要重点关注慢路径。
11）如果这个场景在 fullstack 模式下明显变慢，通常优先怀疑向量模型推理、批量大小或 Qdrant 写入成为瓶颈。

=== 推荐刷新压测结果 ===
压测场景           : 推荐刷新
total_requests     : 200
success_requests   : 200
failed_requests    : 0
concurrency        : 5
total_time_sec     : 2.711
throughput_rps     : 73.78
avg_latency_ms     : 66.69
p50_latency_ms     : 60.79
p95_latency_ms     : 100.84
p99_latency_ms     : 166.70
max_latency_ms     : 250.91

--- 推荐刷新压测说明 ---
这个场景主要看用户画像更新、事件写入、向量召回与结果拼装的整体实时性能。
1）本轮共发起 200 个请求，并发度为 5；成功 200 个，失败 0 个，成功率约 100.00% 。
2）总耗时 total_time_sec=2.711 秒，表示这一轮 推荐刷新 请求整体跑完花了 2.711 秒。
3）吞吐 throughput_rps=73.78，表示当前系统大约每秒能处理 73.78 个推荐刷新请求。
4）平均延迟 avg_latency_ms=66.69 ms，表示单个推荐刷新请求平均耗时约 66.69 毫秒。
5）P50 延迟=60.79 ms，可理解为“典型请求耗时”；一半请求会快于这个值。
6）P95 延迟=100.84 ms，用来看高位延迟是否稳定；如果它明显高于平均值，说明高并发下已有慢请求出现。
7）P99 延迟=166.70 ms，表示极少数最慢请求的水平；它越高，越说明尾部波动越明显。
8）最大延迟 max_latency_ms=250.91 ms，表示本轮最慢的那个请求耗时。
9）本轮没有失败请求，说明在当前参数下接口功能和基本稳定性是正常的。
10）P95 明显高于平均延迟，说明已经出现较明显的尾部放大，需要重点关注慢路径。
11）如果 refresh 的 P95/P99 明显抬高，通常说明用户画像更新、事件写入或向量检索链路里存在串行段或热点资源争用。
```

以下为大压力实际压测结果：
```text
=== 推荐系统压测总览 ===
压测模式           : fullstack
压测场景           : user, item, refresh
每场景请求数       : 2000
并发度             : 10
用户数             : 1000
内容数             : 1000
每次 refresh 行为数: 3
item 分批大小      : 64

--- 总体分析 ---
1）本脚本会把 user、item、refresh 三类请求拆开压测，避免结果互相掩盖。
2）如果 user 很快、item 很慢，优先关注向量化和向量索引写入链路。
3）如果 item 很快、refresh 很慢，优先关注画像更新、事件落库和向量检索链路。
4）建议重点同时观察 avg / P95 / P99，而不只是平均值，因为并发问题通常先体现在尾延迟。
5）当前是 fullstack 模式：结果会覆盖真实 SQLite / 向量化 / Qdrant 链路，更接近线上瓶颈。
6）本轮吞吐最高的场景是：用户创建（74.76 req/s）。
7）本轮高位延迟最大的场景是：内容入库（P95=1211.70 ms）。

=== 用户创建压测结果 ===
压测场景           : 用户创建
total_requests     : 2000
success_requests   : 2000
failed_requests    : 0
concurrency        : 10
total_time_sec     : 26.752
throughput_rps     : 74.76
avg_latency_ms     : 132.83
p50_latency_ms     : 73.99
p95_latency_ms     : 408.59
p99_latency_ms     : 903.65
max_latency_ms     : 1901.65

--- 用户创建压测说明 ---
这个场景主要看批量或高并发建用户时，接口层、SQLite 写入和唯一键处理的开销。
1）本轮共发起 2000 个请求，并发度为 10；成功 2000 个，失败 0 个，成功率约 100.00% 。
2）总耗时 total_time_sec=26.752 秒，表示这一轮 用户创建 请求整体跑完花了 26.752 秒。
3）吞吐 throughput_rps=74.76，表示当前系统大约每秒能处理 74.76 个用户创建请求。
4）平均延迟 avg_latency_ms=132.83 ms，表示单个用户创建请求平均耗时约 132.83 毫秒。
5）P50 延迟=73.99 ms，可理解为“典型请求耗时”；一半请求会快于这个值。
6）P95 延迟=408.59 ms，用来看高位延迟是否稳定；如果它明显高于平均值，说明高并发下已有慢请求出现。
7）P99 延迟=903.65 ms，表示极少数最慢请求的水平；它越高，越说明尾部波动越明显。
8）最大延迟 max_latency_ms=1901.65 ms，表示本轮最慢的那个请求耗时。
9）本轮没有失败请求，说明在当前参数下接口功能和基本稳定性是正常的。
10）P95 明显高于平均延迟，说明已经出现较明显的尾部放大，需要重点关注慢路径。
11）如果 user 场景吞吐偏低，通常优先检查 SQLite 写入频率、事务边界和唯一索引冲突处理。

=== 内容入库压测结果 ===
压测场景           : 内容入库
total_requests     : 2000
success_requests   : 2000
failed_requests    : 0
concurrency        : 10
total_time_sec     : 61.439
throughput_rps     : 32.55
avg_latency_ms     : 305.27
p50_latency_ms     : 145.46
p95_latency_ms     : 1211.70
p99_latency_ms     : 2627.45
max_latency_ms     : 5031.57

--- 内容入库压测说明 ---
这个场景主要看内容写库、向量化与向量索引写入链路的吞吐和尾延迟表现。
1）本轮共发起 2000 个请求，并发度为 10；成功 2000 个，失败 0 个，成功率约 100.00% 。
2）总耗时 total_time_sec=61.439 秒，表示这一轮 内容入库 请求整体跑完花了 61.439 秒。
3）吞吐 throughput_rps=32.55，表示当前系统大约每秒能处理 32.55 个内容入库请求。
4）平均延迟 avg_latency_ms=305.27 ms，表示单个内容入库请求平均耗时约 305.27 毫秒。
5）P50 延迟=145.46 ms，可理解为“典型请求耗时”；一半请求会快于这个值。
6）P95 延迟=1211.70 ms，用来看高位延迟是否稳定；如果它明显高于平均值，说明高并发下已有慢请求出现。
7）P99 延迟=2627.45 ms，表示极少数最慢请求的水平；它越高，越说明尾部波动越明显。
8）最大延迟 max_latency_ms=5031.57 ms，表示本轮最慢的那个请求耗时。
9）本轮没有失败请求，说明在当前参数下接口功能和基本稳定性是正常的。
10）P95 明显高于平均延迟，说明已经出现较明显的尾部放大，需要重点关注慢路径。
11）如果这个场景在 fullstack 模式下明显变慢，通常优先怀疑向量模型推理、批量大小或 Qdrant 写入成为瓶颈。

=== 推荐刷新压测结果 ===
压测场景           : 推荐刷新
total_requests     : 2000
success_requests   : 2000
failed_requests    : 0
concurrency        : 10
total_time_sec     : 31.668
throughput_rps     : 63.15
avg_latency_ms     : 157.95
p50_latency_ms     : 92.86
p95_latency_ms     : 500.26
p99_latency_ms     : 1223.90
max_latency_ms     : 3047.86

--- 推荐刷新压测说明 ---
这个场景主要看用户画像更新、事件写入、向量召回与结果拼装的整体实时性能。
1）本轮共发起 2000 个请求，并发度为 10；成功 2000 个，失败 0 个，成功率约 100.00% 。
2）总耗时 total_time_sec=31.668 秒，表示这一轮 推荐刷新 请求整体跑完花了 31.668 秒。
3）吞吐 throughput_rps=63.15，表示当前系统大约每秒能处理 63.15 个推荐刷新请求。
4）平均延迟 avg_latency_ms=157.95 ms，表示单个推荐刷新请求平均耗时约 157.95 毫秒。
5）P50 延迟=92.86 ms，可理解为“典型请求耗时”；一半请求会快于这个值。
6）P95 延迟=500.26 ms，用来看高位延迟是否稳定；如果它明显高于平均值，说明高并发下已有慢请求出现。
7）P99 延迟=1223.90 ms，表示极少数最慢请求的水平；它越高，越说明尾部波动越明显。
8）最大延迟 max_latency_ms=3047.86 ms，表示本轮最慢的那个请求耗时。
9）本轮没有失败请求，说明在当前参数下接口功能和基本稳定性是正常的。
10）P95 明显高于平均延迟，说明已经出现较明显的尾部放大，需要重点关注慢路径。
11）如果 refresh 的 P95/P99 明显抬高，通常说明用户画像更新、事件写入或向量检索链路里存在串行段或热点资源争用。
```

### 7.2 压测结论

综合小压力与大压力两轮 `fullstack` 压测结果，可以得到以下结论：

1. **整体稳定性达标**：两轮压测中 `user / item / refresh` 三类核心接口均无失败请求，说明当前链路在真实依赖参与下具备较好的可用性与鲁棒性。
2. **推荐刷新满足实时响应目标**：在更接近业务高负载的大压力场景中，`refresh` 接口平均延迟为 `157.95 ms`，P50 为 `92.86 ms`，P95 为 `500.26 ms`，说明大部分推荐刷新请求都能够在亚秒级内完成，能够支撑“用户行为发生后快速反馈推荐结果”的实时体验目标。
3. **用户侧链路表现较稳**：`user` 场景在大压力下仍可达到 `74.76 req/s`，平均延迟 `132.83 ms`，说明用户创建及画像初始化相关链路具备较好的吞吐基础。
4. **当前主要瓶颈集中在内容入库链路**：`item` 场景在大压力下平均延迟 `305.27 ms`、P95 `1211.70 ms`、P99 `2627.45 ms`，明显高于其他场景，表明内容写入、特征处理与索引落库仍是后续优化重点。
5. **系统已具备对外展示和进一步业务验证的基础**：从结果看，当前版本已经能够稳定完成推荐系统的核心闭环，包括用户接入、内容接入、实时推荐刷新与冷启动兜底；若进入更高并发或更大规模数据阶段，建议优先继续优化内容入库效率与高位尾延迟表现。

如果需要对甲方做更偏业务视角的总结，也可以直接表述为：当前系统已经验证了“**可稳定运行、可实时刷新、可支持个性化推荐闭环**”这三项关键能力，其中推荐刷新链路已经达到实时响应要求，内容入库链路则是下一阶段性能优化的重点。
