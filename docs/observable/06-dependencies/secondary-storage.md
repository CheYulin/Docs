# 二级存储依赖（SFS / OBS）

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/common/l2cache/persistence_api.cpp` | `PersistenceApi`：L2 缓存统一入口 |
| `src/datasystem/common/l2cache/sfs_client/sfs_client.{h,cpp}` | SFS（文件系统挂载）实现 |
| `src/datasystem/common/l2cache/obs_client/obs_client.cpp` | OBS（对象存储 HTTP + eSDK）实现 |
| `src/datasystem/worker/object_cache/worker_oc_spill.cpp` | spill 路径（`K_NO_SPACE`）|
| `src/datasystem/common/util/file_util.cpp` | `pread` / `pwrite` 封装（`K_IO_ERROR`）|

---

## 1. 接入方式

| `FLAGS_l2_cache_type` | 客户端实现 | 说明 |
|-----------------------|------------|------|
| `sfs` | `SfsClient` | 挂载路径下本地文件 API（`mkdir / open / read / write / opendir` 等）|
| `obs` | `ObsClient` | 对象存储 HTTP(S) + eSDK（错误形态与 SFS 不同）|
| 其它 | 不初始化 `client_` | 日志：`L2 cache is of type: %s, will not init PersistenceApi.` |

---

## 2. SFS（文件接口）故障检测与消息

| 故障检测 | 细分类型 | 典型 Status / 日志 | 告警建议 |
|----------|---------|-------------------|---------|
| `SfsClient::Init` | 挂载点不可用 | `K_RUNTIME_ERROR`：`SFS path does not exist` / `not a directory` / `not readable` / `not writable` | Init 失败即致命告警 |
| `SfsClient::Init` | gflag 未配置 | `K_INVALID`：`sfs_path gflag can't be empty.` | 配置类告警 |
| `NewDirIfNotExists`（含根目录 `datasystem`、对象目录）| 创建目录失败 | `K_RUNTIME_ERROR`：`Failed to create the given directory.` | 与写路径失败率 |
| `Upload`：open 临时文件 | 创建 / 打开文件失败 | `K_RUNTIME_ERROR`：`Failed to open object file with errno: <strerror>` | I/O 告警 |
| `LoopUpload` | 写入超时 | `K_RUNTIME_ERROR`：`Timed out during uploading object to SFS. Please clear leftovers. Upload to SFS failed.` | 超时告警 + 残留 `_` 文件巡检 |
| `rename` 提交 | 原子提交失败 | `K_RUNTIME_ERROR`：`Rename failed. Upload to SFS failed. errno: %d` | 数据一致性风险告警 |
| `Download` | 对象不存在 | `IfPathExists` → `K_NOT_FOUND`：`Path does not exist` | 业务 / 缓存未命中 |
| `Download` | 读超时 | `K_RUNTIME_ERROR`：`Timed out during downloading object from SFS. Read from SFS failed.` | 读超时 |
| `List` / `ListOneObject` | 打开目录失败 | `K_RUNTIME_ERROR`：`Cannot open the path in SFS for object persistence.` / `Cannot open the path for given object` | 列举失败 |
| `List` | 列举超时 | `K_RUNTIME_ERROR`：`Timed out during listing objects.` | 列举超时 |
| `Delete` / `DeleteOne` | 删除文件失败 | `Failed to remove object` / `Failed to remove tmp object` | 删除失败 |
| `Delete` | 打开父目录失败 | `Failed to open directory` | I/O |
| `Delete` | 部分删除失败汇总 | `K_RUNTIME_ERROR`：`The following objects were not successfully removed: ...` | 批量删除不完整 |
| `GenerateFullPath` | 路径穿越 / 不在工作区 | `K_RUNTIME_ERROR`：`<path> is not in <dsPath>` | 安全 / 配置 |
| `ValidateObjNameWithVersion` | 非法对象名 / 版本 | `K_RUNTIME_ERROR`：`Illegal object name: ...` | 业务错误 |
| `PersistenceApi::UrlEncode` | curl 初始化 / 编码失败 | `K_RUNTIME_ERROR`：`Failed to init curl, encode the object key failed.` / `Failed to curl_easy_escape...` | 不应频繁出现；出现即告警 |
| `ListAllVersion` 分页异常 | OBS / SFS List 分页 stuck | `LOG(ERROR)`：`the nextMarker ... not change!` | 分页死循环巡检 |
| `GetWithoutVersion` / `Del` | 对象在持久化中不存在 | `K_NOT_FOUND_IN_L2CACHE`：`The object is not exist in persistence.` | 与业务删除 / 一致性相关 |
| `Del` | 指定版本未删到 | `K_NOT_FOUND`：`The scenarios is delete object ... maxVerToDelete ... is not found...` | 删除未完成需重试 |

---

## 3. OBS

若 `l2_cache_type == obs`，错误来自 **eSDK / OBS HTTP** 层，消息与码与 SFS 不同；`PersistenceApi` 层仍会打 `invoke save/get/delete` 及成功 / 失败 error code 日志。

若需要与 SFS 同级表格，建议扫 `obs_client.cpp` 中 `RETURN_STATUS` / `LOG(ERROR)` 做 OBS 专表（体量较大，本篇未详展）。

---

## 4. spill 路径

### 4.1 `K_NO_SPACE`

`src/datasystem/worker/object_cache/worker_oc_spill.cpp`：

```cpp
RETURN_STATUS(K_NO_SPACE, "No space when WorkerOcSpill::Spill");
```

### 4.2 `K_IO_ERROR`

`src/datasystem/common/util/file_util.cpp::ReadFile / WriteFile`：

- `pread` / `pwrite` 失败 → `K_IO_ERROR` + errno 细节
- `WriteFile` 恢复日志：失败后 `WriteFile failed...`，恢复后 `WriteFile success again`

---

## 5. Worker `resource.log` 的二级存储字段

| 顺序 | 指标 | 含义 |
|------|------|------|
| 2 | `SPILL_HARD_DISK` | Spill 磁盘用量与比例；高负载或冷数据落盘时与时延、磁盘 IO 相关 |
| 12 | `OBS_REQUEST_SUCCESS_RATE` | `persistenceApi_->GetL2CacheRequestSuccessRate()`（L2 为 OBS 时注册）|
| 20 | `SHARED_DISK` | 共享磁盘维度用量 |

---

## 6. 告警建议

| 告警项 | 信号 | 阈值 |
|--------|------|------|
| OBS 请求成功率下降 | `OBS_REQUEST_SUCCESS_RATE` | < X% |
| `K_IO_ERROR` / `K_NO_SPACE` 突增 | 日志 / 错误码 | > 基线 3σ |
| Spill 磁盘贴上限 | `SPILL_HARD_DISK` 比例 | > 阈值 |
| 写入 / 上传超时 | `Timed out during uploading object to SFS` | 单位时间次数 |
| `nextMarker ... not change!` | 分页死循环 | 出现即告警 |
| 残留临时文件 `_*` 巡检 | 定期扫描挂载路径 | 长期未清理数量 |

---

## 7. 与其它文档的关联

- 错误码 `K_IO_ERROR` / `K_NO_SPACE` / `K_NOT_FOUND_IN_L2CACHE` 的全表：[`../../reliability/03-status-codes.md § 1.1`](../../reliability/03-status-codes.md)
- 故障树 F 段（文件接口故障）：[`../../reliability/04-fault-tree.md § 2.5`](../../reliability/04-fault-tree.md)
- FEMA 故障模式映射：存储类 → FM-004, FM-016，并与 `../03-fault-mode-library.md` 中 PA-002、PA-005 等性能告警联动
