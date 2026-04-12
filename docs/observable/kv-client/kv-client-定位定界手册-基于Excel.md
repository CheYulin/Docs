# KV Client 定位定界手册（基于 Excel）

这份手册用于配合 [`../workbook/kv-client/kv-client-观测-调用链与URMA-TCP.xlsx`](../workbook/kv-client/kv-client-观测-调用链与URMA-TCP.xlsx) 做快速定界。  

**正向 vs 逆向**：**Sheet1 第二列**是 **正向调用树**（根→叶，多行 `└─`）；**排障路径**是 **逆向流程图**——先现象/错误码与日志（**Sheet5**）→ 再 Trace 检索 → 回到 Sheet1 对某一行做确认，**不是**把调用树倒着读。详见 [`../workbook/kv-client/README.md`](../workbook/kv-client/README.md)。

Excel 中建议按 **Sheet5 → Sheet1 → Sheet2/3** 使用：

- `Sheet5_定界-case查表`：**一行一 case**，直接给出 **责任归属**（用户参数 / OS / URMA / 数据系统逻辑 / RPC 框架）、**涉及 URMA 接口**、**涉及 OS 接口**、**一句话定位建议**。排障时先在此表用 Status 或日志关键词筛选。
- `Sheet1_调用链路分析`：Init / 读 / 写按 **case** 分行；**「调用链树（正向·根→叶）」** 列为 **多行树状**（根结点 + `└─` 子调用）+ 分隔线下的 **case/发生位置**；另含 **责任归属**、URMA/OS、**定位建议**、代码锚点。
- `Sheet2_OS系统调用查表`：每行一个 syscall **失败 case**，列含 **责任归属(OS)**、**定位建议**。
- `Sheet3_URMA接口查表`：每行一个 **URMA C 接口** 或连通性检查，列含 **责任归属**、**定位建议**。
- `Sheet4_性能关键路径`：尾延迟与热点（不变）。

---

## 1. 快速使用方法（人工排障）

1. 在 `Sheet5_定界-case查表` 用 **典型现象** 列做筛选，读出 **责任归属** 与 **定位建议**；需要细节时再下钻 Sheet1/2/3。
2. 若未命中 Sheet5，再看 SDK 返回码：
   - `1001/1002/19` → Sheet5 **D02/D14** 或 Sheet1 **RPC框架** 行；
   - `1004/1006` → Sheet5 **D05/D06/D08** 或 Sheet3；
   - `5/6`（`K_RUNTIME_ERROR/K_OUT_OF_MEMORY`）→ Sheet5 **D03/D04/D12** 或 Sheet2 mmap。
3. 在 `Sheet1_调用链路分析` 按接口（Init、MGet/Get、MSet/Put）在 **调用链树（正向·根→叶）** 列中搜符号名或 **【本行 case】** 行，核对 **URMA接口调用** / **OS接口调用** 列是否为具体 `urma_*` 或 syscall。
4. 用“发生位置”列判断进程边界：
   - `client1`：SDK 本地；
   - `client1->worker1`：入口链路；
   - `worker1->worker2`：**Directory（对象目录）** 分片侧（hash ring；日志或仍含 `master` 原文）；
   - `worker1->worker3` 或 `worker3`：数据副本/URMA数据面。
5. 若日志命中 syscall 关键词（`recvmsg`, `mmap`, `close`），跳到 `Sheet2` 对应行看 **定位建议**。
6. 若日志命中 URMA 关键词（`Failed to urma ...`, `poll jfc`, `advise jfr`），跳到 `Sheet3` 对应 **URMA C接口** 行。

---

## 2. 自动化定界建议（日志 -> 责任域）

可以把日志规则做成简单的“模式匹配 + 打分”。

### 2.1 规则优先级

1. **URMA域优先**：命中 `Failed to urma`, `poll jfc`, `advise jfr`, `need to reconnect`。  
2. **OS域次之**：命中 `recvmsg`, `sendmsg`, `mmap`, `invalid fd`, `Unexpected EOF read`。  
3. **RPC域**：命中 `Register client failed`, `rpc timeout`, `unavailable`。  
4. **系统逻辑域**：`K_INVALID`, `K_NOT_FOUND`, `etcd is unavailable` 等业务/依赖逻辑。

### 2.2 最小自动化输出字段

- `接口`（Init/MGet/Get/MSet/Put）
- `发生位置`（client1 / client1->worker1 / worker1->worker2 / worker1->worker3 / worker3）
- `疑似责任域`（URMA / OS / RPC / 系统逻辑）
- `命中规则`（关键词）
- `建议下一步`（优先 Sheet5 case 编号；再查哪个 sheet、哪个模块日志）

### 2.3 伪代码示意

```python
def classify(log_line, status_code):
    if any(k in log_line for k in ["Failed to urma", "poll jfc", "advise jfr", "need to reconnect"]):
        return "URMA", "Sheet3_URMA接口查表"
    if any(k in log_line for k in ["recvmsg", "sendmsg", "mmap", "invalid fd", "Unexpected EOF read"]):
        return "OS", "Sheet2_OS系统调用查表"
    if status_code in [1001, 1002, 19] or "Register client failed" in log_line:
        return "RPC", "Sheet1_调用链路分析"
    return "系统逻辑", "Sheet1_调用链路分析"
```

---

## 3. 典型场景（你关心的 UB -> TCP）

- 当读路径出现：
  - `Prepare UB Get request failed ... fallback to TCP/IP payload`
- 定义：
  - 这是 **URMA 准备失败 + 自动降级 TCP**；
  - 功能可能成功，但性能可能下降；
  - 责任域优先标记为 **URMA/环境**，同时保留“业务成功”状态。

---

## 4. 输出建议（工单模板）

- **结论**：`[域] + [发生位置] + [步骤]`
- **证据**：`StatusCode + 日志关键词 + 代码锚点`
- **影响**：功能失败 / 性能降级 / 可重试
- **动作**：先 `Sheet5` case；再 `Sheet1/2/3` + 哪个模块日志

示例：  
`URMA域 + client1 + UB缓冲准备，命中 "fallback to TCP/IP payload"，判断为UB降级，功能可能成功但性能退化。`

