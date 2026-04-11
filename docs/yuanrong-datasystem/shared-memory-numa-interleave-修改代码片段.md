# shared_memory NUMA Interleave：修改代码片段（参考稿）

面向路径：`yuanrong-datasystem/src/datasystem/common/shared_memory`。  
目标：在 **memfd + mmap** 映射成功后，对整段 `[pointer_, mmapSize_)` 设置 **`MPOL_INTERLEAVE`**，使后续 fault / populate 的页在多个 NUMA 节点间交错分配。

**要点**：若使用 **`MAP_POPULATE`** 或过早 **`fallocate`**，页可能已在默认节点上分配；interleave 应在 **populate 之前** 调用 `mbind`，或去掉首次 mmap 的 `MAP_POPULATE`，在 `mbind` 之后再显式触发 populate。

---

## 1. 构建依赖

**不增加额外动态/静态库**：仅用 **`syscall(__NR_mbind, ...)`**（glibc 已提供），保持现有 `linkopts`（如 `-ldl`）即可。

若某架构头文件未定义 `__NR_mbind`，可在 `numa_mmap_policy.cpp` 里 `#if defined(__NR_mbind)` 包一层，未定义则编译期跳过或打日志降级。

---

## 2. 新增：`mmap/numa_mmap_policy.h`

```cpp
#ifndef DATASYSTEM_COMMON_SHARED_MEMORY_MMAP_NUMA_MMAP_POLICY_H
#define DATASYSTEM_COMMON_SHARED_MEMORY_MMAP_NUMA_MMAP_POLICY_H

#include <cstddef>
#include <string>

#include "datasystem/utils/status.h"

namespace datasystem {
namespace memory {

// 对 [addr, addr+len) 设置 MPOL_INTERLEAVE。nodes 为空表示解析 /sys/devices/system/node/online 得到 online 节点（可再按 meminfo 过滤）。
// 失败时打日志并返回 OK（降级为内核默认策略），或按产品要求返回错误。
Status ApplyNumaInterleaveToMapping(void *addr, size_t len, const std::string &nodes /* "0-3" or "0,2" */);

// Linux 5.14+：在 mbind 之后触发缺页分配；老内核可改为逐页 touch 或保留 MAP_POPULATE 但必须在 mbind 之前关闭。
Status PopulateMappedRegion(void *addr, size_t len);

}  // namespace memory
}  // namespace datasystem

#endif
```

---

## 3. 新增：`mmap/numa_mmap_policy.cpp`（**仅 syscall**，不链接 libnuma）

要点：

- 使用 **`syscall(__NR_mbind, ...)`**；`MPOL_INTERLEAVE` 等与内核一致的常量来自 **`<linux/mempolicy.h>`**（仅头文件，不链接 `numa`）。
- **`nodemask`** 为 `unsigned long` 数组：节点 `n` 对应 **`mask[n / (8*sizeof(unsigned long))] |= (1UL << (n % (8*sizeof(unsigned long))))`**。
- **`maxnode`**（传给内核）：**「掩码中最大节点号 + 1」**（与 `man 2 mbind` 一致）；掩码数组长度至少覆盖 `maxnode` 个 bit。
- 自动模式：读 **`/sys/devices/system/node/online`**（格式如 `0-3`、`0,2`）；可选再读各 node 的 **`meminfo`** 去掉 `MemTotal == 0` 的节点。

```cpp
#include "datasystem/common/shared_memory/mmap/numa_mmap_policy.h"

#include <algorithm>
#include <cerrno>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include <linux/mempolicy.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

#include "datasystem/common/log/log.h"
#include "datasystem/common/util/strings_util.h"
#include "datasystem/utils/status.h"

namespace datasystem {
namespace memory {

namespace {

constexpr unsigned long kBitsPerLong = sizeof(unsigned long) * CHAR_BIT;

// 与内核 nodemask 一致：节点 i -> bit i
void SetNodeBit(std::vector<unsigned long> &mask, unsigned node)
{
    const size_t idx = static_cast<size_t>(node) / kBitsPerLong;
    const unsigned shift = static_cast<unsigned>(node) % static_cast<unsigned>(kBitsPerLong);
    if (mask.size() <= idx) {
        mask.resize(idx + 1, 0UL);
    }
    mask[idx] |= (1UL << shift);
}

bool ParseNodeRangeList(const std::string &spec, std::vector<unsigned> *outNodes)
{
    outNodes->clear();
    std::stringstream ss(spec);
    std::string item;
    while (std::getline(ss, item, ',')) {
        if (item.empty()) {
            continue;
        }
        const auto dash = item.find('-');
        if (dash == std::string::npos) {
            char *end = nullptr;
            const unsigned long v = std::strtoul(item.c_str(), &end, 10);
            if (end == item.c_str() || v > static_cast<unsigned long>(UINT_MAX)) {
                return false;
            }
            outNodes->push_back(static_cast<unsigned>(v));
            continue;
        }
        const std::string left = item.substr(0, dash);
        const std::string right = item.substr(dash + 1);
        char *e1 = nullptr;
        char *e2 = nullptr;
        const unsigned long a = std::strtoul(left.c_str(), &e1, 10);
        const unsigned long b = std::strtoul(right.c_str(), &e2, 10);
        if (e1 == left.c_str() || e2 == right.c_str() || a > b || b > static_cast<unsigned long>(UINT_MAX)) {
            return false;
        }
        for (unsigned long n = a; n <= b; ++n) {
            outNodes->push_back(static_cast<unsigned>(n));
        }
    }
    return !outNodes->empty();
}

bool ReadSysFileTrim(const char *path, std::string *content)
{
    std::ifstream in(path);
    if (!in) {
        return false;
    }
    std::getline(in, *content);
    if (!content->empty() && content->back() == '\n') {
        content->pop_back();
    }
    return true;
}

bool LoadOnlineNodes(std::vector<unsigned> *nodes)
{
    std::string line;
    if (!ReadSysFileTrim("/sys/devices/system/node/online", &line)) {
        return false;
    }
    return ParseNodeRangeList(line, nodes);
}

bool NodeHasMemory(unsigned node)
{
    const std::string path =
        std::string("/sys/devices/system/node/node") + std::to_string(node) + "/meminfo";
    std::ifstream in(path);
    if (!in) {
        return false;
    }
    std::string l;
    while (std::getline(in, l)) {
        if (l.find("MemTotal:") != std::string::npos) {
            unsigned long kb = 0;
            if (std::sscanf(l.c_str(), "MemTotal: %lu kB", &kb) == 1) {
                return kb > 0;
            }
        }
    }
    return false;
}

long DoMbind(void *addr, unsigned long len, int mode, std::vector<unsigned long> &nodemask, unsigned long maxnode,
             unsigned int flags)
{
#if defined(__linux__) && defined(__NR_mbind)
    return syscall(__NR_mbind, reinterpret_cast<unsigned long>(addr), len, static_cast<unsigned long>(mode),
                   nodemask.empty() ? nullptr : nodemask.data(), maxnode, flags);
#else
    (void)addr;
    (void)len;
    (void)mode;
    (void)nodemask;
    (void)maxnode;
    (void)flags;
    errno = ENOSYS;
    return -1;
#endif
}

}  // namespace

Status ApplyNumaInterleaveToMapping(void *addr, size_t len, const std::string &nodes)
{
    if (addr == nullptr || len == 0) {
        return Status::OK();
    }

    std::vector<unsigned> nodeIds;
    if (!nodes.empty()) {
        if (!ParseNodeRangeList(nodes, &nodeIds)) {
            LOG(WARNING) << "Invalid shm_numa_interleave_nodes: " << nodes;
            return Status::OK();
        }
    } else {
        if (!LoadOnlineNodes(&nodeIds)) {
            LOG(WARNING) << "Failed to read NUMA online nodes, skip interleave";
            return Status::OK();
        }
    }

    // 仅保留「有内存」的节点（可按需去掉此过滤以兼容特殊环境）
    std::vector<unsigned> withMem;
    withMem.reserve(nodeIds.size());
    for (unsigned n : nodeIds) {
        if (NodeHasMemory(n)) {
            withMem.push_back(n);
        }
    }
    if (withMem.size() < 2) {
        LOG(INFO) << "Less than 2 NUMA nodes with memory, skip interleave";
        return Status::OK();
    }

    unsigned maxId = 0;
    for (unsigned n : withMem) {
        maxId = std::max(maxId, n);
    }
    const unsigned long maxnode = static_cast<unsigned long>(maxId) + 1UL;

    std::vector<unsigned long> mask;
    const size_t nlongs = (static_cast<size_t>(maxnode) + kBitsPerLong - 1) / kBitsPerLong;
    mask.assign(nlongs, 0UL);
    for (unsigned n : withMem) {
        SetNodeBit(mask, n);
    }

    errno = 0;
    const long rc = DoMbind(addr, static_cast<unsigned long>(len), MPOL_INTERLEAVE, mask, maxnode, 0);
    if (rc != 0) {
        LOG(WARNING) << "syscall mbind MPOL_INTERLEAVE failed: " << StrErr(errno)
                     << " (addr=" << addr << ", len=" << len << ", maxnode=" << maxnode << ")";
        return Status::OK();  // 或 Status(K_RUNTIME_ERROR, ...)
    }
    return Status::OK();
}

Status PopulateMappedRegion(void *addr, size_t len)
{
#ifdef MADV_POPULATE_READ_WRITE
    if (madvise(addr, len, MADV_POPULATE_READ_WRITE) == 0) {
        return Status::OK();
    }
    LOG(WARNING) << "MADV_POPULATE_READ_WRITE failed: " << StrErr(errno);
#endif
    auto *p = static_cast<volatile unsigned char *>(addr);
    const long psz = sysconf(_SC_PAGESIZE);
    const size_t step = psz > 0 ? static_cast<size_t>(psz) : 4096;
    for (size_t off = 0; off < len; off += step) {
        (void)p[off];
    }
    return Status::OK();
}

}  // namespace memory
}  // namespace datasystem
```

说明：

- **`linux/mempolicy.h`**：构建环境需具备内核头（容器/交叉编译时注意 sysroot）；若不便包含，可自行 `#define MPOL_INTERLEAVE 3` 等与当前内核一致（需版本对齐说明）。
- 生产环境仍建议将 **`nodes` 与 cgroup `cpuset.mems` 求交**，否则 `mbind` 常见 **`EINVAL`**。
- 若页已在错误节点上，可评估带 **`MPOL_MF_MOVE`** 的再次 `mbind`（权限与延迟），本文档从略。

---

## 4. 修改：`mmap/mem_mmap.cpp`（gflag + populate 顺序）

在文件顶部 flags 区域增加：

```cpp
DS_DEFINE_bool(enable_shm_numa_interleave, false,
               "If true, apply MPOL_INTERLEAVE to memfd mmap region before populate (MemMmap only).");
DS_DEFINE_string(shm_numa_interleave_nodes, "",
                 "NUMA node list for interleave, e.g. 0-3 or 0,2. Empty: auto-detect memory nodes.");
```

在 `MemMmap::Initialize` 中，在调用 `SetupFileMapping` **之前**拆分 `populate` 与 `mmap` flags：

```cpp
Status MemMmap::Initialize(uint64_t size, bool populate, bool hugepage)
{
    // ... memfd_create 与 flags/hugepage 逻辑保持不变 ...

    unsigned int flags = MAP_SHARED;
    if (hugepage) {
        flags = MAP_SHARED | MAP_HUGETLB;
    }

    const bool deferPopulate = populate && FLAGS_enable_shm_numa_interleave;
    if (populate && !deferPopulate) {
        flags |= MAP_POPULATE;
    }

    type_ = "memory";
    Status rc = SetupFileMapping(size, flags, true);
    if (!rc.IsOk()) {
        return rc;
    }

    if (FLAGS_enable_shm_numa_interleave) {
        rc = ApplyNumaInterleaveToMapping(pointer_, static_cast<size_t>(mmapSize_),
                                          FLAGS_shm_numa_interleave_nodes);
        if (!rc.IsOk()) {
            return rc;
        }
    }
    if (deferPopulate) {
        rc = PopulateMappedRegion(pointer_, static_cast<size_t>(mmapSize_));
        if (!rc.IsOk()) {
            return rc;
        }
    }

    RETURN_IF_NOT_OK(RegisterFastTransportMemory(pointer_, mmapSize_));
    RETURN_IF_NOT_OK(RegisterHostMemory(pointer_, mmapSize_));
    return Status::OK();
}
```

注意：上文替换了原 `Initialize` 末尾「`SetupFileMapping` 成功后直接 Register」的结构；请与当前仓库中 **`#ifdef BUILD_HETERO`** 块对齐合并，避免丢分支。

---

## 5. 修改：`mmap/base_mmap.cpp`（可选，与 `fallocate` 时序）

若 **`Commit`/`fallocate` 在 mbind 之前就把页钉在单节点**，interleave 仍可能失效。可选策略：

- 在 **`enable_shm_numa_interleave`** 为 true 时，对 `MemMmap` 延后首次大规模 `fallocate`，直到 `ApplyNumaInterleaveToMapping` 之后；或  
- 保持现有顺序，但接受「已 commit 的页」需 **`MPOL_MF_MOVE`** 才能迁移（实现与测试成本更高）。

---

## 6. 将新文件加入构建列表

### CMakeLists.txt

```cmake
mmap/numa_mmap_policy.cpp
```

### BUILD.bazel `srcs` + `hdrs`

```python
"mmap/numa_mmap_policy.cpp",
# hdrs:
"mmap/numa_mmap_policy.h",
```

---

## 7. 验证建议

- 运行进程后查看 `/proc/<pid>/numa_maps`，确认对应 anon/tmpfs 映射在多节点有分布。  
- 在绑定单 NUMA 节点的容器中应自动降级或仅单节点 mask，避免启动失败。

---

## 8. 与 libnuma 对比

当前文档默认路径为 **syscall + `/sys` 解析**，**不链接 `libnuma`**。若后续需要与 `numastat` 等工具完全一致的节点语义，再考虑引入 libnuma 作为可选依赖。

---

*本文档为设计参考片段，落地前需与当前分支 `mem_mmap.cpp` 实际代码（含 `BUILD_HETERO` 等）做一次三路合并与单测。*
