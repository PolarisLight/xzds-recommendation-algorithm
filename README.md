# xzds-recommendation-algorithm

一个基于 **FastAPI + SQLite + Qdrant + 轻量文本向量模型** 的推荐系统示例项目，用于演示：

- 用户画像向量初始化与更新
- 内容（文本标签）入库与向量化索引
- 基于用户行为（view / like / favorite）的实时个性化推荐
- 冷启动场景下的最新内容回退
- Qdrant 集合和点位的调试接口

---

## 1. 项目介绍

本项目核心思路：

1. **内容侧建模**：将每条内容（title / description / tags）转换为文本向量，并写入 Qdrant。
2. **用户侧建模**：每个用户维护一个 384 维画像向量（SQLite 保存）。
3. **行为驱动更新**：用户发生 `view / like / favorite` 行为时，使用不同权重更新用户向量。
4. **召回推荐**：用用户向量到 Qdrant 做相似检索，返回 Top-K 内容。
5. **冷启动兜底**：当用户画像仍接近零向量时，返回按 `created_at` 倒序的最新内容。

默认配置（见 `demo_rec/config.py`）：

- 向量维度：`384`
- Qdrant 地址：`http://localhost:6333`
- 集合名：`items_demo`
- 默认推荐数量：`20`

---

## 2. 运行与使用

## 2.1 环境准备

- Python 3.10+
- 本地或容器中的 Qdrant（默认 `6333` 端口）

安装依赖：

```bash
cd demo_rec
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
uvicorn demo_rec.app:app --host 0.0.0.0 --port 8000 --reload
```

> 如果你是直接运行单文件脚本（例如 `python demo_rec/perf_test_high_load.py`），项目也兼容。

启动时会自动执行：

- SQLite 表初始化
- Qdrant 集合初始化

## 2.4 查看交互式 API 文档

服务启动后可访问：

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## 2.5 安装轻量文本向量模型

默认优先按下面的顺序找模型：1）环境变量 `EMBEDDING_MODEL_NAME` 指定的路径或模型名；2）项目内的 `demo_rec/all-MiniLM-L6-v2` 本地目录；3）最后才回退到 Hugging Face 上的 `sentence-transformers/all-MiniLM-L6-v2`。如果解析到的是本地目录，代码会自动开启 `local_files_only=True`，不再请求 Hugging Face。若你想强制离线，也可以额外设置 `EMBEDDING_LOCAL_FILES_ONLY=1`。

应用启动时还会额外打印 `APP EMBEDDING_MODEL_NAME`、`APP EMBEDDING_MODEL_IS_LOCAL` 和 `APP EMBEDDING_LOCAL_FILES_ONLY`，便于确认实际加载的是哪个模型目录。

高压全链路压测时，如果想把用户初始化、内容初始化、刷新请求拆开看，可以使用 `demo_rec/perf_test_high_load.py` 新增的 `--bootstrap-item-batch-size` 参数，把 item 初始化拆成多个批次提交；最终输出也会单独展示 user bootstrap、item bootstrap 和 refresh 请求的耗时。

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

## 4. 全部接口文档

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

  curl -X POST "http://localhost:8000/init/users" -H "Content-Type: application/json" --data-binary @demo_rec/data/users_batch.json
curl -X POST "http://localhost:8000/init/items" -H "Content-Type: application/json" --data-binary @demo_rec/data/items_batch.json
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
  "collections": ["items_demo"]
}
```

---

### 4.8 `GET /qdrant/collections/{collection_name}`

返回指定集合详情（向量配置、点数量等）。

**示例**：

```bash
curl "http://127.0.0.1:8000/qdrant/collections/items_demo"
```

---

### 4.9 `POST /qdrant/collections/{collection_name}/points/scroll`

分页查看集合中的点（调试/排查用）。

**请求体**：`QdrantScrollRequest`

**示例**：

```bash
curl -X POST "http://127.0.0.1:8000/qdrant/collections/items_demo/points/scroll" -H "Content-Type: application/json" -d "{\"limit\":5,\"with_payload\":true,\"with_vector\":false}"
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

项目附带脚本：`demo_rec/test_data_ingest.py`，可用于验证 SQLite 入库。

```bash
python demo_rec/test_data_ingest.py
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
- 若要调整推荐数量、Qdrant 地址、集合名、模型名，可修改 `demo_rec/config.py`。

---

## 7. 性能测试结果说明

### 7.0 压测脚本说明

仓库额外提供了一个纯 Python 压测脚本 `demo_rec/perf_test_high_load.py`，支持两种模式：

- `--mode isolated`：隔离 Qdrant、SQLite、向量模型，只测试 FastAPI 应用层和推荐接口逻辑，适合快速定位代码层瓶颈。
- `--mode fullstack`：连接真实运行中的推荐服务，能够把 **向量化、入库、Qdrant 检索** 等真实依赖全部纳入延迟统计，更接近线上真实表现。

示例：

```bash
# 快速看应用层开销
python demo_rec/perf_test_high_load.py --mode isolated --requests 2000 --concurrency 300 --users 1000 --items 5000

# 测真实全链路延迟（需要先启动服务，并准备好 SQLite / Qdrant / 向量模型）
python demo_rec/perf_test_high_load.py --mode fullstack --base-url http://127.0.0.1:8000 --bootstrap-data --requests 2000 --concurrency 300 --users 1000 --items 5000
```

脚本会输出总耗时、吞吐量（RPS）以及平均 / P50 / P95 / P99 延迟，便于快速评估推荐刷新链路在高负载场景下的表现。若要评估真实线上延迟，应优先使用 `fullstack` 模式。脚本对 `502/503/504` 默认会自动重试，并在最终结果中汇总失败请求数量与失败样例，而不是在第一次网关错误时直接退出。

### 7.1 实际压测结果

以下为一次实际压测结果：

```text
=== Recommendation App Load Benchmark ===
total_requests     : 2000
concurrency        : 300
total_time_sec     : 28.161
throughput_rps     : 71.02
avg_latency_ms     : 14.00
p50_latency_ms     : 13.73
p95_latency_ms     : 15.22
p99_latency_ms     : 17.98
max_latency_ms     : 38.42
```

### 7.2 各指标含义

- `total_requests`: 本轮压测的总请求数，这里表示共发起了 `2000` 个推荐刷新请求。
- `concurrency`: 并发数，这里表示压测过程中同时最多有 `300` 个请求在执行。
- `total_time_sec`: 跑完整轮压测所消耗的总时间，这里是 `28.161` 秒。
- `throughput_rps`: 吞吐量（Requests Per Second），表示系统平均每秒可处理多少个请求；这里约为 `71.02` 次/秒。
- `avg_latency_ms`: 平均延迟，表示单个请求平均耗时；这里约为 `14.00ms`。
- `p50_latency_ms`: 50 分位延迟，表示有 `50%` 的请求在 `13.73ms` 内完成，可以理解为典型请求耗时。
- `p95_latency_ms`: 95 分位延迟，表示有 `95%` 的请求在 `15.22ms` 内完成，只有少量长尾请求更慢。
- `p99_latency_ms`: 99 分位延迟，表示有 `99%` 的请求在 `17.98ms` 内完成。
- `max_latency_ms`: 本轮压测中最慢请求的耗时，这里为 `38.42ms`。

### 7.3 结果解读

从这组数据来看，该推荐算法在实时性上已经可以满足一般的在线推荐刷新需求：

- 平均延迟仅 `14ms`，说明单次推荐刷新响应很快。
- `P95` 仅 `15.22ms`、`P99` 仅 `17.98ms`，说明绝大多数请求都能在很短时间内完成，长尾延迟控制得比较稳定。
- 最慢请求也只有 `38.42ms`，整体没有出现明显的抖动或严重阻塞。

综合来看，这个算法在**实时性**方面已经具备较好的可用性，适合作为实时推荐刷新链路的基础实现。
