# DataSystem 日志配置说明

## 一、概述

DataSystem 提供两套日志配置体系，分别用于**进程启动时一次性配置**和**运行时热更新**。

| 配置方式 | 配置文件 | 适用场景 | `log_monitor` | `minloglevel` |
|----------|----------|----------|:-------------:|:-------------:|
| 启动前配置 | `worker_config.json` | 部署时设置 | ✅ 支持 | ✅ 支持 |
| 运行时热更新 | `datasystem.config` | 动态调整 | ✅ 支持（加入白名单后） | ✅ 支持（加入白名单后） |
| 环境变量 | 进程环境 | Client 启动前 | ✅ 支持 | ✅ 支持 |

> **注意**：`log_monitor` 和 `minloglevel` 原本不在 `flagNameTrustList_` 白名单中，无法通过 `datasystem.config` 热更新。

---

## 二、`log_monitor` 和 `minloglevel` 参数说明

### 2.1 `minloglevel`（日志级别门槛）

| 属性 | 值 |
|------|-----|
| 类型 | int32 |
| 默认值 | 0 |
| 可选值 | `0` = INFO（所有级别）、`1` = WARNING、`2` = ERROR、`3` = FATAL |

低于此级别的日志不会被记录。例如设置为 `2` 时，只有 ERROR 和 FATAL 级别的日志会写入文件。

### 2.2 `log_monitor`（日志监控开关）

| 属性 | 值 |
|------|-----|
| 类型 | bool |
| 默认值 | true |
| 说明 | 控制是否启用 AccessRecorder（接口性能与资源观测日志） |

关闭后可减少日志量，适用于不需要观测日志的场景。

---

## 三、Workaround 1：Client 侧代码配置（Header-only 方式）

> **适用场景**：客户不想修改 DataSystem 源码，只想在应用代码中通过环境变量配置日志参数。
>
> **文件**：`log_env_config.h`（Header-only，客户直接拷贝到项目中使用）
>
> **路径**：`yuanrong-datasystem-agent-workbench/docs/deploy/log_env_config.h`
>
> **原理**：通过 `setenv()` 在进程内设置环境变量，在 `Logging::Start()` 初始化前一次性生效。

### 3.1 使用方式

将 `log_env_config.h` 拷贝到客户项目中，在创建任何 DataSystem Client 之前调用：

```cpp
#include "log_env_config.h"

int main() {
    // ===== 在创建任何 DataSystem Client 之前配置 =====

    // 方式 A：一键关闭所有日志
    datasystem::LogEnvConfig::DisableAllLogging();

    // 方式 B：自定义配置（Builder 模式，可链式调用）
    datasystem::LogEnvConfig::Builder()
        .SetMinLogLevel(3)       // 0=INFO, 1=WARNING, 2=ERROR, 3=FATAL
        .SetLogMonitor(false)    // 关闭观测日志
        .Apply();

    // ===== 然后再初始化 Client =====
    datasystem::ConnectOptions connectOptions;
    connectOptions.etcdAddresses = { "127.0.0.1:2379" };
    auto client = std::make_shared<datasystem::KVClient>(connectOptions);
    (void)client->Init();

    // ... 业务逻辑 ...
}
```

### 3.2 支持的参数

| Builder 方法 | 环境变量 | 可选值 | 默认值 |
|-------------|---------|--------|--------|
| `SetMinLogLevel(int)` | `DATASYSTEM_MIN_LOG_LEVEL` | `0`=INFO, `1`=WARNING, `2`=ERROR, `3`=FATAL | `0` |
| `SetLogMonitor(bool)` | `DATASYSTEM_LOG_MONITOR_ENABLE` | `true`/`false` | `true` |

### 3.3 便捷方法

```cpp
// 一键关闭所有日志（等价于 minloglevel=3 + log_monitor=false）
LogEnvConfig::DisableAllLogging();
```

### 3.4 注意事项

| 注意事项 | 说明 |
|---------|------|
| **调用时机** | `Apply()` **必须**在创建任何 DataSystem Client **之前**调用 |
| **线程安全** | 单线程直接使用；多线程需确保 `Apply()` 在子线程创建前调用 |
| **只生效一次** | 环境变量在 `Logging::Start()` 时读取，后续修改不影响已初始化的 Client |
| **无依赖** | Header-only，无需链接额外库 |

---

## 四、代码修改（加入白名单）

> **适用场景**：通过 `datasystem.config` 文件热更新 `minloglevel` 和 `log_monitor`。
>
> **注意**：以下代码修改已在 DataSystem 仓库中执行。如使用 Workaround 1（Header-only 方式），无需执行此修改。

如尚未将 `log_monitor` 和 `minloglevel` 加入白名单，需修改以下文件：

### 4.1 修改 `flags.h`

**文件**：`yuanrong-datasystem/src/datasystem/common/util/gflag/flags.h`

**位置**：`flagNameTrustList_` 成员变量

```cpp
// flags.h:176
const std::unordered_set<std::string> flagNameTrustList_{
    "v",
    "log_async_queue_size",
    "log_compress",
    "log_rate_limit",
    "max_log_file_num",
    "arena_per_tenant",
    "node_dead_timeout_s",
    "client_reconnect_wait_s",
    "spill_file_max_size_mb",
    "spill_file_open_limit",
    "spill_size_limit",
    "heartbeat_interval_ms",
    "add_node_wait_time_s",
    "async_delete",
    "auto_del_dead_node",
    "cross_cluster_get_data_from_worker",
    "enable_hash_ring_self_healing",
    "shared_disk_arena_per_tenant",
    "enable_lossless_data_exit_mode",
    "minloglevel",     // <-- 新增
    "log_monitor",     // <-- 新增
#ifdef WITH_TESTS
    "inject_actions"
#endif
};
```

---

## 五、`datasystem.config` 模板（运行时热更新）

### 5.1 完整模板

```bash
# ~/datasystem/config/datasystem.config
# 用途: Client/Worker 运行时热更新 flags
# 轮询间隔: Worker 10s, Client 1s
# 注意: 修改后自动生效（通过文件 mtime 检测）

# ==================== 日志配置 ====================
-v=0
-log_async=true
-log_async_queue_size=1024
-log_compress=true
-log_rate_limit=0
-max_log_file_num=5
-log_only_write_info_file=true
-minloglevel=0
-log_monitor=true
```

### 5.2 字段说明

| flag | 默认值 | 说明 |
|------|--------|------|
| `-v` | 0 | VLOG 级别 |
| `-log_async` | true | 是否异步写日志 |
| `-log_async_queue_size` | 1024 | 异步队列大小 |
| `-log_compress` | true | 是否压缩旧日志（.gz） |
| `-log_rate_limit` | 0 | 日志速率限制（0=不限） |
| `-max_log_file_num` | 5 | 每个 severity 保留的最大文件数 |
| `-log_only_write_info_file` | true | true=只写 INFO 文件，false=同时写 WARNING/ERROR |
| `-minloglevel` | 0 | 日志级别门槛（0=INFO, 1=WARNING, 2=ERROR, 3=FATAL） |
| `-log_monitor` | true | 是否开启接口性能与资源观测日志 |

### 5.3 部署方式

**Client 侧**：
```bash
# 方式1: 环境变量指定路径
export DATASYSTEM_CLIENT_CONFIG_PATH=/path/to/datasystem.config

# 方式2: 默认路径（默认 ~/.datasystem/config/datasystem.config）
mkdir -p ~/.datasystem/config
cp datasystem.config ~/.datasystem/config/datasystem.config
```

**Worker 侧（K8s）**：
修改 Helm Chart 的 ConfigMap：

```yaml
# k8s/helm_chart/datasystem/templates/configmap.yaml
data:
  datasystem.config: |-
    -v=0
    -log_async=true
    -log_async_queue_size=1024
    -log_compress=true
    -log_rate_limit=0
    -max_log_file_num=5
    -log_only_write_info_file=true
    -minloglevel=0
    -log_monitor=true
```

---

## 六、`worker_config.json` 模板（启动前配置）

通过 `dscli generate_config` 生成，或手动修改后使用 `dscli start -f worker_config.json` 部署。

```json
{
    "minloglevel": {
        "value": "0",
        "description": "设置记录冗余日志的最低级别，0=INFO, 1=WARNING, 2=ERROR, 3=FATAL"
    },
    "log_monitor": {
        "value": "true",
        "description": "是否开启接口性能与资源观测日志"
    }
}
```

---

## 七、环境变量配置（仅 Client）

Client 启动前通过环境变量一次性设置：

```bash
# 关闭日志监控
export DATASYSTEM_LOG_MONITOR_ENABLE=false

# 提高日志级别门槛（只记录 WARNING 及以上）
export DATASYSTEM_MIN_LOG_LEVEL=2

# 设置日志目录
export DATASYSTEM_CLIENT_LOG_DIR=/var/log/datasystem

./your_client_app
```

### 环境变量完整列表

| 环境变量 | 对应 Flag | 默认值 |
|---------|-----------|--------|
| `DATASYSTEM_LOG_MONITOR_ENABLE` | `FLAGS_log_monitor` | true |
| `DATASYSTEM_MIN_LOG_LEVEL` | `FLAGS_minloglevel` | 0 |
| `DATASYSTEM_LOG_V` | `FLAGS_v` | 0 |
| `DATASYSTEM_LOG_ASYNC_ENABLE` | `FLAGS_log_async` | true |
| `DATASYSTEM_LOG_ASYNC_QUEUE_SIZE` | `FLAGS_log_async_queue_size` | 1024 |
| `DATASYSTEM_LOG_COMPRESS` | `FLAGS_log_compress` | true |
| `DATASYSTEM_LOG_RATE_LIMIT` | `FLAGS_log_rate_limit` | 0 |
| `DATASYSTEM_CLIENT_LOG_DIR` | `FLAGS_log_dir` | `~/.datasystem/logs` |
| `DATASYSTEM_LOG_TO_STDERR` | `FLAGS_logtostderr` | false |
| `DATASYSTEM_ALSO_LOG_TO_STDERR` | `FLAGS_alsologtostderr` | false |
| `DATASYSTEM_STD_THRESHOLD` | `FLAGS_stderrthreshold` | 2 (ERROR) |
| `DATASYSTEM_LOG_RETENTION_DAY` | `FLAGS_log_retention_day` | 0 |

---

## 八、配置优先级

当同一 flag 同时通过多种方式配置时，按以下优先级生效（**高优先级覆盖低优先级**）：

```
环境变量 > 命令行 flags > worker_config.json / datasystem.config > 代码默认值
```

对于 Client：
```
环境变量 > Logging::Start() 中 InitClientConfig > 命令行 flags > datasystem.config > 代码默认值
```

---

## 九、快速参考

### 场景：运行时动态关闭 `log_monitor`（减少日志量）

**方法：通过 `datasystem.config` 热更新**

```bash
# 修改配置
cat > ~/.datasystem/config/datasystem.config << 'EOF'
-log_monitor=false
EOF

# 等待 Worker/Client 轮询检测到文件变化（Worker 约10s，Client 约1s）
# 验证
grep "log_monitor" ~/.datasystem/config/datasystem.config
```

### 场景：提高日志级别减少日志量

**方法：设置 `minloglevel=2`**（只记录 ERROR 和 FATAL）

```bash
cat > ~/.datasystem/config/datasystem.config << 'EOF'
-minloglevel=2
EOF
```

### 场景：部署时一次性关闭 `log_monitor`

**方法：修改 `worker_config.json`**

```json
"log_monitor": {
    "value": "false"
}
```

然后执行 `dscli start -f worker_config.json`。

### 场景：Client 代码中关闭所有日志（推荐）

**方法：使用 Header-only 方式（Workaround 1）**

```cpp
#include "log_env_config.h"

int main() {
    // 一键关闭所有日志
    datasystem::LogEnvConfig::DisableAllLogging();

    // 初始化 Client
    datasystem::ConnectOptions connectOptions;
    connectOptions.etcdAddresses = { "127.0.0.1:2379" };
    auto client = std::make_shared<datasystem::KVClient>(connectOptions);
    (void)client->Init();
}
```

---

## 十、相关文件索引

| 文件 | 说明 |
|------|------|
| `yuanrong-datasystem-agent-workbench/docs/deploy/log_env_config.h` | Header-only 日志配置工具（Workaround 1） |
| `src/datasystem/common/util/gflag/flags.h` | `flagNameTrustList_` 白名单定义 |
| `src/datasystem/common/util/gflag/flags.cpp` | `ValidateFlagName`、`UpdateFlagParameter` |
| `src/datasystem/common/log/logging.cpp` | 日志初始化、`InitClientConfig`（环境变量覆盖） |
| `src/datasystem/client/client_flags_monitor.cpp` | Client 侧 `FlagsMonitor`（1s 轮询） |
| `worker_main.cpp` | Worker 侧 `MonitorConfigFile`（10s 节流） |
| `k8s/helm_chart/datasystem/templates/configmap.yaml` | K8s 部署 `datasystem.config` 模板 |
| `cli/deploy/conf/worker_config.json` | `dscli` 启动配置模板 |
