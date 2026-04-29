# L2Cache 类图与接口体系

## 概述

L2Cache（二级缓存）模块位于 `yuanrong-datasystem/src/datasystem/common/l2cache/` 目录下，提供了对接多种存储后端的能力，包括华为云 OBS 对象存储、SFS Turbo 文件系统、以及分布式磁盘存储。

## 核心类关系图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           PersistenceApi (抽象工厂类)                              │
│  - Create() / CreateShared() 工厂方法根据 l2_cache_type 创建具体实现               │
│  - UrlEncode() 静态工具方法                                                       │
└─────────────────────────┬───────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
┌───────────────────┐             ┌───────────────────────────────┐
│ObjectPersistenceApi│             │  AggregatedPersistenceApi      │
│  (OBS/SFS模式)    │             │    (DISTRIBUTED_DISK模式)      │
│                   │             │                               │
│ 持有 unique_ptr   │             │  持有 unique_ptr<StorageClient>│
│   <L2CacheClient> │             │                               │
└───────┬───────────┘             └───────────────┬───────────────┘
        │                                         │
        ▼                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        L2CacheClient (抽象基类)                                   │
│  + Init()                                                                    │
│  + Upload(objectPath, timeoutMs, body, asyncElapse)                           │
│  + List(objectPrefix, timeoutMs, listIncompleteVersions, listResp)             │
│  + Download(objectPath, timeoutMs, content)                                  │
│  + Delete(objects, asyncElapse)                                              │
│  + GetRequestSuccessRate()                                                    │
└───────────┬─────────────────────────────────┬─────────────────────────────────┘
            │                                 │
            ▼                                 ▼
┌───────────────────────┐           ┌───────────────────────┐
│      ObsClient        │           │      SfsClient        │
│   (OBS对象存储)        │           │   (SFS Turbo)         │
│                       │           │                       │
│ - endPoint_          │           │ - sfsPath_            │
│ - bucketName_        │           │ - dsPath_             │
│ - credentialManager_ │           │ - writeChunkSize_    │
│ - httpClient_        │           │ - readChunkSize_     │
│                       │           │                       │
│ + StreamingUpload()   │           │ + LoopUpload()        │
│ + MultiPartUpload()  │           │ + ListAllObjects()    │
│ + SignRequest()      │           │ + IsSfsUsable()       │
└───────────────────────┘           └───────────────────────┘

        ┌─────────────────────────────────────────────────────────────────────────┐
        │                     StorageClient (抽象基类)                              │
        │  + Init()                                                               │
        │  + Save(objectKey, version, timeoutMs, body, asyncElapse, writeMode, ttl)│
        │  + Get(objectKey, version, timeoutMs, content)                         │
        │  + GetWithoutVersion(objectKey, timeoutMs, minVersion, content)         │
        │  + Delete(objectKey, maxVerToDelete, deleteAllVersion, asyncElapse)     │
        │  + PreloadSlot() / MergeSlot() / CleanupLocalSlots()                   │
        └─────────────────────────────┬───────────────────────────────────────────┘
                                      │
                                      ▼
        ┌─────────────────────────────────────────────────────────────────────────┐
        │                         SlotClient (分布式磁盘模式)                        │
        │                                                                          │
        │  - sfsPath_           : 共享文件系统根路径                               │
        │  - slotNum_           : 槽数量 (默认128)                                │
        │  - slots_             : unordered_map<uint32, unique_ptr<Slot>>         │
        │  - compactThread_     : 后台压缩线程                                     │
        │                                                                          │
        │  + GetSlotId(key)     : 根据objectKey计算槽ID                           │
        │  + RepairSlot()       : 修复中断的写入                                   │
        │  + CompactSlot()      : 压缩槽                                           │
        │  + MergeSlot()        : 合并远端worker槽                                 │
        │  + PreloadSlot()      : 预加载远端worker槽                              │
        │  + CleanupLocalSlots(): 清理本地槽                                        │
        └─────────────────────────────┬───────────────────────────────────────────┘
                                      │
                                      ▼
        ┌─────────────────────────────────────────────────────────────────────────┐
        │                              Slot                                        │
        │                                                                          │
        │  - manifest_    : SlotManifest (槽清单文件)                              │
        │  - index_      : SlotIndexCodec (索引编码)                               │
        │  - dataFile_   : 数据文件                                               │
        │  - compactor_  : SlotCompactor (压缩器)                                  │
        │                                                                          │
        │  负责单个槽内的对象存储、索引管理、压缩                                    │
        └─────────────────────────────────────────────────────────────────────────┘
```

## 工厂创建逻辑

```cpp
PersistenceApi::Create()
       │
       ├─── l2_cache_type == "distributed_disk"
       │         │
       │         ▼
       │    AggregatedPersistenceApi(SlotClient)
       │              │
       │              ▼
       │         SlotClient ──→ Slot (多个，按slotId路由)
       │
       └─── 其他 (obs / sfs / none)
                 │
                 ▼
            ObjectPersistenceApi
                 │
                 ├─── obs ──→ ObsClient (HTTP REST API)
                 ├─── sfs ──→ SfsClient (文件系统)
                 └─── none ─→ 不创建client (空实现)
```

## 接口层次说明

### 1. 北向接口：PersistenceApi

位置：`src/datasystem/common/l2cache/persistence_api.h`

这是二级缓存的核心抽象接口，定义如下：

```cpp
class PersistenceApi {
    virtual ~PersistenceApi() = default;

    static std::unique_ptr<PersistenceApi> Create();
    static std::shared_ptr<PersistenceApi> CreateShared();

    virtual Status Init() = 0;

    // 保存对象到二级缓存
    virtual Status Save(const std::string &objectKey, uint64_t version, int64_t timeoutMs,
                        const std::shared_ptr<std::iostream> &body, uint64_t asyncElapse = 0,
                        WriteMode writeMode = WriteMode::NONE_L2_CACHE, uint32_t ttlSecond = 0) = 0;

    // 获取指定版本对象
    virtual Status Get(const std::string &objectKey, uint64_t version, int64_t timeoutMs,
                       std::shared_ptr<std::stringstream> &content) = 0;

    // 获取最新版本对象
    virtual Status GetWithoutVersion(const std::string &objectKey, int64_t timeoutMs, uint64_t minVersion,
                                     std::shared_ptr<std::stringstream> &content) = 0;

    // 删除对象
    virtual Status Del(const std::string &objectKey, uint64_t maxVerToDelete, bool deleteAllVersion,
                       uint64_t asyncElapse = 0, ...) = 0;

    virtual Status PreloadSlot(...) = 0;
    virtual Status MergeSlot(...) = 0;
    virtual Status CleanupLocalSlots() = 0;
};
```

### 2. 南向接口：L2CacheClient

位置：`src/datasystem/common/l2cache/l2cache_client.h`

```cpp
class L2CacheClient {
    virtual Status Init() = 0;
    virtual Status Upload(const std::string &objectPath, int64_t timeoutMs,
                          const std::shared_ptr<std::iostream> &body, uint64_t asyncElapse = 0) = 0;
    virtual Status List(const std::string &objectPrefix, int64_t timeoutMs, bool listIncompleteVersions,
                        std::shared_ptr<GetObjectInfoListResp> &listResp) = 0;
    virtual Status Download(const std::string &objectPath, int64_t timeoutMs,
                            std::shared_ptr<std::stringstream> &content) = 0;
    virtual Status Delete(const std::vector<std::string> &objects, uint64_t asyncElapse = 0) = 0;
    virtual std::string GetRequestSuccessRate() = 0;
};
```

## 支持的二级缓存类型

定义在 `src/datasystem/common/l2cache/l2_storage.h`：

```cpp
enum class L2StorageType : uint32_t {
    NONE = 0,
    OBS = 1u,           // 华为云OBS对象存储
    SFS = 1u << 2,      // SFS Turbo文件存储
    DISTRIBUTED_DISK = 1u << 3  // 分布式磁盘存储
};
```

配置参数 `l2_cache_type` 支持的值：`none`、`obs`、`sfs`、`distributed_disk`

## 设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| **Factory** | `PersistenceApi::Create()` | 根据配置类型创建不同实现 |
| **Strategy** | `L2CacheClient` | 不同存储后端实现统一接口 |
| **Adapter** | `ObsClient` / `SfsClient` | 将不同存储接口适配为统一 `L2CacheClient` |
| **Template Method** | `StorageClient` vs `PersistenceApi` | 抽象层级不同，操作粒度不同 |

## SlotClient 内部结构 (分布式磁盘模式)

```
SlotClient
  │
  ├─── 128 个 Slot (按 objectKey hash 分桶)
  │         │
  │         └─── Slot
  │               ├─── manifest_  (清单文件: 记录所有对象版本)
  │               ├─── index_    (索引: 加速对象查找)
  │               └─── dataFile_ (数据文件: 存储实际内容)
  │
  └─── 后台压缩线程 (定期压缩多个 Slot)
          │
          └─── SlotCompactor
```

## 目录结构

```
src/datasystem/common/l2cache/
├── l2cache_client.h           # 抽象基类 (L2CacheClient)
├── l2cache_client.cpp
├── persistence_api.h          # 核心工厂抽象类
├── persistence_api.cpp        # 工厂实现 + UrlEncode
├── storage_client.h           # StorageClient 抽象类 (聚合存储)
├── object_persistence_api.h  # OBS/SFS 模式实现
├── object_persistence_api.cpp
├── aggregated_persistence_api.h # 聚合模式实现
├── aggregated_persistence_api.cpp
├── l2_storage.h              # L2StorageType 枚举定义
├── l2_storage.cpp
├── l2cache_object_info.h     # 对象信息结构体
├── get_object_info_list_resp.h # 列表响应结构体
│
├── obs_client/               # OBS 对象存储客户端
│   ├── obs_client.h
│   ├── obs_client.cpp
│   ├── obs_signature.h/cpp
│   ├── obs_xml_util.h/cpp
│   └── cloud_service_rotation.h/cpp
│
├── sfs_client/               # SFS Turbo 客户端
│   ├── sfs_client.h
│   └── sfs_client.cpp
│
└── slot_client/              # 分布式磁盘 Slot 存储
    ├── slot_client.h
    ├── slot_client.cpp
    ├── slot.h
    ├── slot.cpp
    ├── slot_manifest.h/cpp
    ├── slot_index_codec.h/cpp
    ├── slot_compactor.h/cpp
    ├── slot_writer.h/cpp
    ├── slot_snapshot.h/cpp
    ├── slot_takeover_planner.h/cpp
    ├── slot_transfer.h
    ├── slot_file_util.h/cpp
    └── slot_internal_config.h
```

## 南向对接新存储

如需对接新的存储后端（如 Redis），需要：

1. **继承 `L2CacheClient` 抽象基类**
2. **在 `ObjectPersistenceApi::Init()` 中注册新的客户端类型**
3. **添加对应的 gflag 配置参数**

参考实现：`ObsClient` 和 `SfsClient` 作为具体实现示例。
