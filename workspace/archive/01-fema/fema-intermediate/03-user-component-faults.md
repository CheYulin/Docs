# FMEA 中间分析：用户层 & 组件生命周期故障

## 1. 用户层故障模式

用户层涉及业务实例调用 SDK 的参数校验和业务逻辑。

### 1.1 用户层故障详表

| FM编号 | 故障模式 | 边界域 | StatusCode | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 关键日志 |
|-------|---------|--------|------------|---------|---------|------------|--------|---------|
| FM-022 | 入参非法 | User | 2 | 业务传入非法参数、key 格式错误、超长 value | 请求直接被拒绝 | 否 | Ⅳ类 | `Invalid` |
| FM-017 | 对象不存在 | User | 3 | 业务查询不存在的 key、已过期被清理 | 返回 NOT_FOUND | 否 | Ⅳ类 | `K_NOT_FOUND` |
| FM-023 | 业务 last_rc 部分 key 重试 | User | 混合 | 业务侧超时重试、部分成功部分失败 | 数据一致性风险 | 部分 | Ⅲ类 | `last_rc` |

## 2. 组件生命周期故障模式

组件层涉及 SDK/Worker 进程生命周期管理。

### 2.1 组件生命周期故障详表

| FM编号 | 故障模式 | 边界域 | StatusCode | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 关键日志 |
|-------|---------|--------|------------|---------|---------|------------|--------|---------|
| FM-001 | SDK 进程异常退出 | 组件 | 22/23 | SDK crash、OOM、coredump | 业务实例不可用 | 是 | Ⅱ类 | `Worker is exiting now` |
| FM-002 | Worker 进程退出/重启 | 组件 | 31/32 | Worker crash、容器重启、OOM | 数据访问中断 | 是 | Ⅱ类 | `Worker is exiting now` / `K_SCALE_DOWN` |
| FM-003 | Worker 进程挂死 | 组件 | 31 | 死锁、BusyLoop、资源耗尽 | 业务请求卡死 | 是 | Ⅰ类 | `Cannot receive heartbeat from worker` |
| FM-021 | 扩缩容/内存策略拒绝 | 组件 | 32/6 | K_SCALING / K_LRU_HARD_LIMIT / 内存不足 | 扩缩容失败 | 部分 | Ⅲ类 | `K_SCALING` |

## 3. 组件生命周期关键代码路径

### 3.1 Worker HealthCheck
```
文件: worker_oc_service_impl.cpp::HealthCheck
故障点: CheckLocalNodeIsExiting
错误码: 31
日志: Worker is exiting now
```

### 3.2 扩缩容拒绝
```
文件: worker_oc_service_multi_publish_impl.cpp
故障点: meta_is_moving
错误码: 32
日志: The cluster is scaling
```

### 3.3 首次心跳超时
```
文件: listen_worker.cpp
故障点: 首次心跳超时
错误码: 23
日志: Cannot receive heartbeat
```

### 3.4 Worker 退出
```
文件: worker_oc_service_impl.cpp
故障点: 进程退出
错误码: 31/32
日志: Worker is exiting now / K_SCALE_DOWN
```

## 4. 扩缩容故障详表

| 场景 | 故障模式 | 边界域 | StatusCode | 可能原因 | 故障影响 |
|-----|---------|--------|------------|---------|---------|
| 业务实例扩容 | 共享内存通道建立失败 | OS | 1001/1002 | Worker 容器重启、内存不足 | 扩容失败 |
| 业务实例缩容 | 共享内存释放失败 | OS | 1002 | Worker 连接断开 | 缩容不完整 |
| KVCache worker 扩容 | 元数据迁移失败 | ETCD | 25 | Master 超时、元数据不可用 | 迁移中断 |
| KVCache worker 缩容 | 数据迁移失败 | URMA | 1004/1006 | UB 连接断开、迁移超时 | 数据丢失风险 |
| KVCache worker 升级 | SDK 切换失败 | 组件 | 31/32 | Worker 重启、连接超时 | 升级失败 |

## 5. 故障检测与处理

### 5.1 组件生命周期检测

| 预期检测方法 | 版本现状 |
|------------|---------|
| Worker 心跳检测 | ✅ 已实现 - listen_worker.cpp |
| 进程退出告警 | ✅ 已实现 - HealthCheck |
| 扩缩容状态检测 | ✅ 已实现 - K_SCALING |
| LRU 内存压力检测 | ✅ 已实现 - K_LRU_HARD_LIMIT |

### 5.2 故障处理方法

| 故障模式 | 预期处理 | 版本现状 |
|---------|---------|---------|
| SDK 进程退出 | 业务侧重启 SDK | ✅ 自愈依赖业务 |
| Worker 进程退出 | 自动重拉、流量切换 | ✅ 已实现 - 流量迁移 |
| Worker 挂死 | 强制重启 + 告警 | ⚠️ 当前依赖外部监控 |
| 扩缩容拒绝 | 等待 + 重试 | ✅ 已实现 |

## 6. 改进建议

| 优先级 | 改进项 | 说明 |
|-------|-------|-----|
| P0 | Worker 挂死检测 | 增加 busy loop 检测，避免卡死 |
| P1 | 扩缩容失败自动回滚 | 扩缩容失败时自动回滚到之前状态 |
| P2 | SDK 进程健康自愈 | SDK 退出后自动重启 |
