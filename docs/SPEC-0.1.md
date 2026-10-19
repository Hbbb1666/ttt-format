# TTT 文件格式规范 v0.1（容器层）

- 状态：草案（Draft），容器层已实现并有测试；语义层未定义
- 关键字：MUST / SHOULD / MAY 按 RFC 2119 解释
- 字节序：全部**大端**（Big Endian）

## 1. 总览

一个 `.ttt` 文件由三段构成，**没有尾部数据、没有额外填充**：

```
+----------+------------+------------+--------------+----------------+
| 固定头 56B | 清单 JSON  | 负载 ZIP    |              |                |
+----------+------------+------------+--------------+----------------+
 offset 0    offset 56    offset 56+h   总长度 = 56 + h + p
```

| 段 | 长度 | 内容 |
|---|---|---|
| 固定头 | 56 B | magic、版本、flags、两段长度、负载 SHA-256 |
| 清单 header | `header_len` | UTF-8 JSON，无 BOM |
| 负载 payload | `payload_len` | ZIP 容器（可为空，长度为 0） |

## 2. 固定头（56 字节）

| 偏移 | 字段 | 类型 | 说明 |
|---|---|---|---|
| 0 | `magic` | 4 B | 必须为 `54 54 54 31`（ASCII `TTT1`） |
| 4 | `major` | u16 | 主版本；v0.1 实现写 `1` |
| 6 | `minor` | u16 | 次版本；v0.1 实现写 `0` |
| 8 | `flags` | u32 | 位标记；未知位**必须忽略** |
| 12 | `header_len` | u32 | 清单 JSON 字节数，`0 < header_len <= 1 MiB` |
| 16 | `payload_len` | u64 | 负载字节数，`<= 4 GiB`（实现可再收紧） |
| 24 | `body_sha256` | 32 B | SHA-256(header 字节 ‖ payload 字节) |

读取端 **MUST** 校验：`magic` 正确、`文件总长 == 56 + header_len + payload_len`、`SHA-256(header ‖ payload)` 匹配（头部也必须被摘要覆盖，否则清单可被静默改写）。任一不符即 `BAD_MAGIC` / `TRUNCATED` / `BAD_SHA`。

## 3. 清单（header JSON）

### 3.1 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema` | string | 是 | 必须匹配 `ttt/<major>.<minor>`，用于自描述 |
| `major` | integer | 是 | 与固定头一致 |
| `minor` | integer | 是 | 与固定头一致 |
| `created` | string | 是 | RFC 3339 UTC 时间戳 |
| `generator` | string | 是 | 写入方标识，如 `ttt-cli/0.1.0` |
| `content` | object | 是 | **语义层**：由业务约定，容器只要求是 JSON 对象 |
| `attachments` | array | 是 | 与 ZIP 条目一一对应的附件清单，可为空数组 |

### 3.2 附件条目

```json
{"path": "files/a.bin", "size": 1234, "sha256": "<64 hex>"}
```

`path` 是 ZIP 内的**相对路径**，必须满足第 5 节路径规则；`size` 与 `sha256` 必须与 ZIP 实条目一致，否则 `BAD_ATTACHMENT`。

### 3.3 扩展

写入端 **MAY** 增加未知字段；读取端 **MUST** 忽略未知字段并在 `warnings` 中提示（不视为错误）。

## 4. 负载（ZIP）

- **MUST** 是合法 ZIP（`PK\x03\x04` 或空负载）。
- 条目数 **MUST** `<= 10000`。
- 全部条目解压后总大小 **MUST** `<= min(2 GiB, payload_len * 20)`，防 zip 炸弹（`ZIP_LIMIT`）。
- 条目 **MUST NOT** 是目录条目、符号链接或设备文件。
- 条目名 **MUST** 为 UTF-8；同名条目 **MUST NOT** 重复。
- 压缩方式不限（store / deflate 均可）。

## 5. 路径规则（防路径穿越）

条目名与附件 `path` 必须同时满足：

1. 非空、长度 `<= 512` 字节；
2. 不以 `/` 开头，不含 `\`，不含盘符前缀（`^[A-Za-z]:`）；
3. 按 `/` 切分后不含 `.`、`..`、空段；
4. 不含 NUL 与其它控制字符。

违反即 `UNSAFE_PATH`，读取端 **MUST** 拒绝整个文件（不允许"跳过坏条目继续读"）。

## 6. 版本与兼容

| 场景 | 读取端行为 |
|---|---|
| `major` 与实现不同 | 拒绝：`UNSUPPORTED_VERSION` |
| `minor` 高于实现 | 尽力读取，`warnings` 记录 |
| 未知 `flags` 位 | 忽略，`warnings` 记录 |
| 未知 header 字段 | 忽略，`warnings` 记录 |

写入端 **MUST** 只写当前实现已知字段；新增字段需先修订本规范。

## 7. 错误码

| 码 | 含义 |
|---|---|
| `BAD_MAGIC` | 头部 magic 不是 `TTT1` |
| `TRUNCATED` | 长度不足或与头部声明不一致 |
| `BAD_HEADER` | 清单 JSON 非法 / 缺字段 / 类型错 |
| `BAD_SHA` | 负载 SHA-256 不匹配 |
| `UNSUPPORTED_VERSION` | major 不支持 |
| `UNSAFE_PATH` | 条目名/附件路径违规 |
| `ZIP_LIMIT` | 条目数或解压体积超限 |
| `BAD_ATTACHMENT` | 清单与 ZIP 条目不一致 |
| `IO_ERROR` | 读写失败 |

## 8. MIME 与后缀（草案）

- 私有/早期阶段：`application/vnd.hbbb1666.ttt+zip`（vendor tree，RFC 6838）
- 目标公开类型（待 IANA 注册）：`application/ttt+zip`
- 后缀：`.ttt`（大小写不敏感的比较由平台负责）

## 9. 待定（语义层，v0.2 讨论）

`content` 的字段集合、是否允许内嵌引用外部资源、缩略图约定、签名段（当前只有 SHA-256 完整性，无身份认证）。
