# XZDS Recommendation Algorithm API 全量接口文档

> 本文档补齐仓库中的完整接口说明，覆盖当前代码里实际存在的所有 HTTP 接口、请求/响应结构、字段约束、可选配置项，以及 V1 / V2 之间的差异。

## 1. 文档范围

当前仓库包含两个可运行版本：

- `xzds_rec_v1.app:app`
- `xzds_rec_v2.app:app`

两者的接口集合基本一致，主要差异在：

1. **V2 的 `/init/items` 支持 `batch_size` 参数**，可控制批量向量入库大小。
2. **V2 的 `/feed/refresh` 增加了按用户维度的串行锁**，降低同一用户并发刷新时的画像竞争。
3. **V2 的部分初始化实现做了批处理优化**，但接口路径和核心业务语义与 V1 保持兼容。

如果你只准备启动一个版本，默认优先参考仓库 README 中的 **V1 启动方式**。如果你要压测或验证批量初始化能力，建议同时参考 V2 的差异说明。

---

## 2. Base URL 与文档入口

默认服务地址：

```text
http://127.0.0.1:8000
```

交互式文档：

- Swagger UI：`/docs`
- ReDoc：`/redoc`

例如：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/redoc`

---

## 3. 版本差异总览

| 接口 | V1 | V2 | 说明 |
|---|---|---|---|
| `POST /init/users` | ✅ | ✅ | 均支持批量初始化用户 |
| `POST /init/items` | ✅ | ✅ | V2 额外支持 `batch_size` |
| `POST /users` | ✅ | ✅ | 创建单个用户 |
| `POST /items` | ✅ | ✅ | 创建单条内容 |
| `POST /feed/refresh` | ✅ | ✅ | 刷新推荐流；V2 带用户级锁 |
| `GET /readyz` | ✅ | ✅ | 就绪检查 |
| `GET /qdrant/collections` | ✅ | ✅ | 列集合 |
| `GET /qdrant/collections/{collection_name}` | ✅ | ✅ | 查集合详情 |
| `POST /qdrant/collections/{collection_name}/points/scroll` | ✅ | ✅ | 分页查看点数据 |

---

## 4. 通用数据模型

以下模型名称来自代码中的 Pydantic 定义，Swagger 中也会以相同结构展示。

### 4.1 `UserInitRequest`

用于 `POST /init/users`。

```json
{
  "users": ["user_001", "user_002"]
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `users` | `string[]` | 是 | 要初始化的用户 ID 列表 |

补充说明：

- 接口本身未限制长度，但批量过大时建议分批请求。
- 用户 ID 在数据库里作为唯一标识使用，建议由业务侧保证稳定唯一。

---

### 4.2 `ItemData`

用于 `POST /items`，也作为 `POST /init/items` 中 `items[]` 的元素结构。

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

字段说明：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `item_id` | `int` | 是 | - | 内容唯一 ID，同时作为向量点 ID |
| `title` | `string` | 是 | - | 内容标题 |
| `description` | `string` | 是 | - | 内容描述 |
| `modality` | `string` | 是 | - | 内容模态标记，例如 `image_text` |
| `author_id` | `string` | 否 | `""` | 作者 ID |
| `tags` | `string[]` | 否 | `[]` | 标签列表 |
| `image_url` | `string` | 否 | `""` | 图片地址，仅业务透传，不参与 embedding |
| `created_at` | `string` | 否 | `""` | 创建时间，建议使用 `YYYY-MM-DD HH:MM:SS` |

可接受配置建议：

- `modality` 当前代码没有枚举限制，**任意字符串都可接受**。
- `tags` 可为空数组。
- `image_url` 可为空字符串。
- `created_at` 若用于冷启动最新内容排序，建议传可字典序排序的标准时间字符串。

---

### 4.3 `ItemInitRequest`

#### V1 结构

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

#### V2 结构

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
  ],
  "batch_size": 64
}
```

字段说明：

| 字段 | 版本 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|---|
| `items` | V1/V2 | `ItemData[]` | 是 | - | 要批量初始化的内容列表 |
| `batch_size` | V2 | `int` | 否 | `64` | Qdrant 批量 upsert 的分批大小 |

`batch_size` 可接受范围：

- **V2 only**
- 最小值：`1`
- 最大值：`1000`

---

### 4.4 `CreateUserRequest`

```json
{
  "user_id": "user_001"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `user_id` | `string` | 是 | 单个用户 ID |

---

### 4.5 `EventRequest`

用于 `POST /feed/refresh`。

```json
{
  "user_id": "user_001",
  "recent_item_ids": [1001, 1002],
  "recent_events": ["view", "like"],
  "k": 20
}
```

字段说明：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `user_id` | `string` | 是 | - | 用户 ID |
| `recent_item_ids` | `int[]` | 否 | `[]` | 最近发生行为的内容 ID 列表 |
| `recent_events` | `string[]` | 否 | `[]` | 最近行为类型列表 |
| `k` | `int` | 否 | `20` | 返回推荐条数 |

`recent_events` 当前代码中实际支持且带权重的行为类型：

| 事件类型 | 权重 |
|---|---|
| `view` | `0.08` |
| `like` | `0.15` |
| `favorite` | `0.25` |

注意事项：

1. `recent_item_ids` 与 `recent_events` 的长度必须一致，否则返回 `400`。
2. 如果某个 `item_id` 在向量索引中不存在，该条行为会被跳过，不会中断整个请求。
3. 代码没有为 `k` 设置最小值校验；如果传 `0`，运行时会回退到默认值 `20`。
4. 对于未知事件类型，权重解释取决于推荐逻辑实现；业务上建议只传 `view / like / favorite`。

---

### 4.6 `QdrantScrollRequest`

用于 `POST /qdrant/collections/{collection_name}/points/scroll`。

```json
{
  "limit": 10,
  "with_payload": true,
  "with_vector": false
}
```

字段说明：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `limit` | `int` | 否 | `10` | 本次滚动查询返回的点数量 |
| `with_payload` | `bool` | 否 | `true` | 是否返回 payload |
| `with_vector` | `bool` | 否 | `false` | 是否返回向量 |

---

## 5. 全量接口说明

## 5.1 `POST /init/users`

### 作用

批量初始化用户画像记录。

### 请求体

`UserInitRequest`

### 请求示例

```bash
curl -X POST 'http://127.0.0.1:8000/init/users' \
  -H 'Content-Type: application/json' \
  -d '{"users":["user_001","user_002"]}'
```

### 响应示例

```json
{
  "message": "users initialized",
  "count": 2
}
```

### 响应字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `message` | `string` | 固定成功消息 |
| `count` | `int` | 本次请求处理的用户数量 |

### 版本差异

- **V1**：逐个调用用户创建逻辑。
- **V2**：走批量创建实现，性能更好。

---

## 5.2 `POST /init/items`

### 作用

批量初始化内容数据，包含两部分：

1. 写入 SQLite 内容表。
2. 写入 Qdrant 向量索引。

### 请求体

- V1：`ItemInitRequest(items)`
- V2：`ItemInitRequest(items, batch_size)`

### 请求示例（V1）

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
        "image_url": "https://example.com/a.jpg",
        "created_at": "2026-03-15 12:00:00"
      }
    ]
  }'
```

### 请求示例（V2）

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
        "image_url": "https://example.com/a.jpg",
        "created_at": "2026-03-15 12:00:00"
      }
    ],
    "batch_size": 64
  }'
```

### 响应示例（V1）

```json
{
  "message": "items initialized",
  "count": 1
}
```

### 响应示例（V2）

```json
{
  "message": "items initialized",
  "count": 1,
  "batch_size": 64
}
```

### 说明

- `item_id` 既是业务内容 ID，也是 Qdrant 点 ID。
- 若存在重复 ID，最终行为取决于数据库唯一键与向量 upsert 逻辑。
- V2 适合大批量入库初始化。

---

## 5.3 `POST /users`

### 作用

创建单个用户。

### 请求体

`CreateUserRequest`

### 请求示例

```bash
curl -X POST 'http://127.0.0.1:8000/users' \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user_003"}'
```

### 响应示例

```json
{
  "message": "user created",
  "user_id": "user_003"
}
```

---

## 5.4 `POST /items`

### 作用

创建单条内容，并实时写入向量索引。

### 请求体

`ItemData`

### 请求示例

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

### 响应示例

```json
{
  "message": "item created",
  "item_id": 1002
}
```

---

## 5.5 `POST /feed/refresh`

### 作用

推荐系统核心接口：接收用户最近行为，更新画像并返回推荐结果。

### 处理流程

1. 校验用户是否存在。
2. 校验 `recent_item_ids` 与 `recent_events` 长度是否一致。
3. 逐条读取内容向量并按行为权重更新用户画像。
4. 记录行为事件。
5. 更新用户画像向量。
6. 如果画像仍接近零向量，则返回最新内容兜底。
7. 否则按向量相似度返回个性化推荐结果。

### 请求体

`EventRequest`

### 请求示例

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

### 成功响应示例：个性化推荐

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

### 成功响应示例：冷启动兜底

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
      "image_url": "https://example.com/a.jpg",
      "created_at": "2026-03-15 12:00:00"
    }
  ]
}
```

### 响应字段

顶层字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | `string` | 当前请求用户 |
| `mode` | `string` | `personalized` 或 `cold_start_latest` |
| `items` | `array` | 推荐结果列表 |

`items[]` 中可能出现的字段：

| 字段 | personalized | cold_start_latest | 说明 |
|---|---|---|---|
| `item_id` | ✅ | ✅ | 内容 ID |
| `score` | ✅ | ❌ | 相似度分数，仅个性化召回返回 |
| `title` | ✅ | ✅ | 标题 |
| `description` | ✅ | ✅ | 描述 |
| `modality` | ✅ | ✅ | 模态 |
| `author_id` | ✅ | ✅ | 作者 ID |
| `tags` | ✅ | ✅ | 标签 |
| `image_url` | ✅ | ✅ | 图片地址 |
| `created_at` | ✅ | ✅ | 创建时间 |

### 常见错误

#### 404 用户不存在

```json
{
  "detail": "user not found"
}
```

#### 400 长度不一致

```json
{
  "detail": "recent_item_ids and recent_events length mismatch"
}
```

### 版本差异

- **V1**：直接刷新。
- **V2**：同一 `user_id` 上加串行锁，减少并发更新用户画像时的竞争问题。

---

## 5.6 `GET /readyz`

### 作用

服务就绪检查，同时返回 Qdrant 连通状态。

### 请求示例

```bash
curl 'http://127.0.0.1:8000/readyz'
```

### 响应示例

```json
{
  "status": "ok",
  "qdrant": {
    "ok": true,
    "error": ""
  }
}
```

### 响应字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `string` | `ok` 或 `degraded` |
| `qdrant.ok` | `bool` | Qdrant 是否可用 |
| `qdrant.error` | `string` | 异常信息；正常时一般为空 |

---

## 5.7 `GET /qdrant/collections`

### 作用

列出当前 Qdrant 中的集合名称。

### 请求示例

```bash
curl 'http://127.0.0.1:8000/qdrant/collections'
```

### 响应示例

```json
{
  "collections": ["items_xzds_rec_v1"]
}
```

---

## 5.8 `GET /qdrant/collections/{collection_name}`

### 作用

返回指定集合详情，常用于确认向量维度、点数量、索引状态等。

### 路径参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `collection_name` | `string` | 是 | Qdrant 集合名 |

### 请求示例

```bash
curl 'http://127.0.0.1:8000/qdrant/collections/items_xzds_rec_v1'
```

### 响应说明

该接口透传 Qdrant SDK 返回结构，因此字段会随 Qdrant 版本略有变化。通常可看到：

- 向量配置
- 点数量
- 分片/segment 相关信息
- 优化器配置等元数据

如果你需要固定字段校验，建议以你运行环境中的 `/docs` 实际输出为准。

---

## 5.9 `POST /qdrant/collections/{collection_name}/points/scroll`

### 作用

用于调试和排查，分页读取某个集合中的向量点。

### 路径参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `collection_name` | `string` | 是 | 目标集合名 |

### 请求体

`QdrantScrollRequest`

### 请求示例

```bash
curl -X POST 'http://127.0.0.1:8000/qdrant/collections/items_xzds_rec_v1/points/scroll' \
  -H 'Content-Type: application/json' \
  -d '{"limit":5,"with_payload":true,"with_vector":false}'
```

### 响应示例

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
        "image_url": "https://example.com/a.jpg",
        "created_at": "2026-03-15 12:00:00"
      },
      "vector": null
    }
  ],
  "next_page_offset": 1001
}
```

### 响应字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `points` | `array` | 当前页返回的点 |
| `points[].id` | `int|string` | 点 ID |
| `points[].payload` | `object|null` | 点 payload；取决于 `with_payload` |
| `points[].vector` | `array|null` | 向量；仅 `with_vector=true` 时返回 |
| `next_page_offset` | `int|string|null` | 下一页 offset |

---

## 6. 所有可接受配置项

本节补齐“接口能接受的所有配置”和“服务运行时的所有核心配置”。

## 6.1 请求级配置项

### `/init/items` 的 `batch_size`（仅 V2）

| 字段 | 类型 | 默认值 | 可接受范围 | 说明 |
|---|---|---|---|---|
| `batch_size` | `int` | `64` | `1 ~ 1000` | 控制批量 upsert Qdrant 时每批大小 |

### `/feed/refresh` 的 `k`

| 字段 | 类型 | 默认值 | 建议范围 | 说明 |
|---|---|---|---|---|
| `k` | `int` | `20` | `1 ~ 100`（业务建议） | 召回条数；传 `0` 时会回退默认值 |

### `/qdrant/.../scroll` 的调试参数

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `limit` | `int` | `10` | 每页拉取条数 |
| `with_payload` | `bool` | `true` | 是否查看 payload |
| `with_vector` | `bool` | `false` | 是否查看向量本体 |

---

## 6.2 行为类型配置

当前代码内置行为权重如下：

| 行为 | 权重 | 含义 |
|---|---|---|
| `view` | `0.08` | 浏览 |
| `like` | `0.15` | 点赞 |
| `favorite` | `0.25` | 收藏 |

如果要扩展新的行为类型，例如 `share` / `comment`，需要同步修改对应版本的 `config.py` 与画像更新逻辑。

---

## 6.3 环境变量配置

以下为当前项目代码实际读取的环境变量。

### 通用环境变量（V1 / V2 都支持）

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `QDRANT_URL` | `""` | 外部 Qdrant 服务地址；为空时通常走本地存储模式 |
| `QDRANT_LOCAL_PATH` | `xzds_rec_v*/qdrant_data` | 本地嵌入式 Qdrant 数据目录 |
| `SQLITE_PATH` | `xzds_rec_v*/xzds_rec_v*.sqlite` | SQLite 数据库文件路径 |
| `EMBEDDING_MODEL_NAME` | 自动解析 | 向量模型名或本地目录 |
| `EMBEDDING_LOCAL_FILES_ONLY` | `false` 或自动变 `true` | 是否只使用本地模型文件 |

### 版本差异环境变量

| 环境变量 | V1 | V2 | 说明 |
|---|---|---|---|
| `QDRANT_COLLECTION` | ❌ 不支持环境变量覆盖 | ✅ 支持 | V1 固定为 `items_xzds_rec_v1`，V2 默认 `items_xzds_rec_v2` |

### `EMBEDDING_MODEL_NAME` 的解析顺序

系统按以下顺序选择模型：

1. 如果设置了 `EMBEDDING_MODEL_NAME`：
   - 若它是本地存在路径，则直接使用该目录。
   - 若它不是本地路径，则当作 Hugging Face 模型名使用。
2. 如果未设置，则尝试项目内置目录：
   - V1：`models/all-MiniLM-L6-v2`
   - V2：`models/all-MiniLM-L6-v2`
3. 若仍未找到，则回退：
   - `sentence-transformers/all-MiniLM-L6-v2`

### `EMBEDDING_LOCAL_FILES_ONLY` 的实际行为

以下任一条件成立时，最终都会按“仅本地文件”模式处理：

- 显式设置：`1`
- 显式设置：`true`
- 显式设置：`yes`
- `EMBEDDING_MODEL_NAME` 解析结果本身就是本地存在目录

---

## 6.4 固定内部配置

这些参数不是接口请求直接传入的，但属于文档中应说明的“系统当前可配置能力边界”。

| 配置项 | 当前值 | 说明 |
|---|---|---|
| `VECTOR_DIM` | `384` | 用户向量与内容向量维度 |
| `DEFAULT_K` | `20` | 默认推荐条数 |
| `QDRANT_COLLECTION` | V1=`items_xzds_rec_v1`，V2 默认=`items_xzds_rec_v2` | 向量集合名 |
| `ITEM_INIT_BATCH_SIZE` | V2=`64` | V2 批量初始化默认分批大小 |

---

## 7. 推荐调用顺序

建议的联调顺序如下：

1. 调用 `POST /init/users` 初始化用户。
2. 调用 `POST /init/items` 或 `POST /items` 初始化内容。
3. 调用 `GET /readyz` 确认服务可用。
4. 调用 `POST /feed/refresh` 验证推荐刷新。
5. 如需排查向量是否已写入，再调用：
   - `GET /qdrant/collections`
   - `GET /qdrant/collections/{collection_name}`
   - `POST /qdrant/collections/{collection_name}/points/scroll`

---

## 8. 最小联调示例

### 8.1 初始化用户

```bash
curl -X POST 'http://127.0.0.1:8000/init/users' \
  -H 'Content-Type: application/json' \
  -d '{"users":["user_demo_001"]}'
```

### 8.2 初始化内容

```bash
curl -X POST 'http://127.0.0.1:8000/init/items' \
  -H 'Content-Type: application/json' \
  -d '{
    "items": [
      {
        "item_id": 9001,
        "title": "示例内容",
        "description": "推荐系统联调用测试内容",
        "modality": "image_text",
        "author_id": "author_demo",
        "tags": ["测试", "演示"],
        "image_url": "",
        "created_at": "2026-03-20 10:00:00"
      }
    ]
  }'
```

### 8.3 刷新推荐

```bash
curl -X POST 'http://127.0.0.1:8000/feed/refresh' \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id":"user_demo_001",
    "recent_item_ids":[9001],
    "recent_events":["like"],
    "k":5
  }'
```

---

## 9. 文档维护建议

如果后续新增接口，建议同时更新以下三个位置，避免 README、Swagger 和离线文档不一致：

1. `xzds_rec_v1/app.py` / `xzds_rec_v2/app.py` 中的 Pydantic 模型与路由。
2. 本文档 `docs/api-reference.md`。
3. `README.md` 中的导航与快速示例。
