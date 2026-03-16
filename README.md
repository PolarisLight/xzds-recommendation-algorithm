# xzds-recommendation-algorithm

一个基于 **FastAPI + SQLite + Qdrant + 多模态向量模型** 的推荐系统示例项目，用于演示：

- 用户画像向量初始化与更新
- 内容（图文）入库与向量化索引
- 基于用户行为（view / like / favorite）的实时个性化推荐
- 冷启动场景下的最新内容回退
- Qdrant 集合和点位的调试接口

---

## 1. 项目介绍

本项目核心思路：

1. **内容侧建模**：将每条内容（title / description / tags / image_url）转换为向量，并写入 Qdrant。
2. **用户侧建模**：每个用户维护一个 512 维画像向量（SQLite 保存）。
3. **行为驱动更新**：用户发生 `view / like / favorite` 行为时，使用不同权重更新用户向量。
4. **召回推荐**：用用户向量到 Qdrant 做相似检索，返回 Top-K 内容。
5. **冷启动兜底**：当用户画像仍接近零向量时，返回按 `created_at` 倒序的最新内容。

默认配置（见 `demo_rec/config.py`）：

- 向量维度：`512`
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

## 2.2 启动 Qdrant（示例）

如果本机尚未运行 Qdrant，可用 Docker 快速启动：

```bash
docker run -p 6333:6333 qdrant/qdrant
```

## 2.3 启动服务

在仓库根目录执行：

```bash
uvicorn demo_rec.app:app --host 0.0.0.0 --port 8000 --reload --app-dir demo_rec
```

启动时会自动执行：

- SQLite 表初始化
- Qdrant 集合初始化

## 2.4 查看交互式 API 文档

服务启动后可访问：

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

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
    "recent_item_ids":[1001,1002],
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
curl 'http://127.0.0.1:8000/readyz'
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
curl 'http://127.0.0.1:8000/qdrant/collections'
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
curl 'http://127.0.0.1:8000/qdrant/collections/items_demo'
```

---

### 4.9 `POST /qdrant/collections/{collection_name}/points/scroll`

分页查看集合中的点（调试/排查用）。

**请求体**：`QdrantScrollRequest`

**示例**：

```bash
curl -X POST 'http://127.0.0.1:8000/qdrant/collections/items_demo/points/scroll' \
  -H 'Content-Type: application/json' \
  -d '{"limit":5,"with_payload":true,"with_vector":false}'
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

- `image_url` 可为空；图片向量提取失败时会自动退化为纯文本向量。
- `created_at` 建议使用可排序字符串格式（如 `YYYY-MM-DD HH:MM:SS`），以保证冷启动最新内容排序正确。
- 行为权重默认：
  - `view`: 0.08
  - `like`: 0.15
  - `favorite`: 0.25
- 若要调整推荐数量、Qdrant 地址、集合名、模型名，可修改 `demo_rec/config.py`。
