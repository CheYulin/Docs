# MGet / 批量读：调用链「行」模板（你举的最长路径示例）

本文约定：**表头下一行起**，**第二列「调用链段」** 按 **编号 + 跨进程语义** 书写；同一接口多张表时，**先铺最长路径**，异常分支另起行或另表（见文末）。

**命名**：`worker1` = **入口 Worker**（SDK `stub` 连到的实例）；`worker2` = **元数据查询对端**（实现上常为 Master/etcd 访问链上的逻辑角色，填表时可用 **实际进程名/IP** 替换）；`worker3` = **数据所在 Worker**（远端副本侧，发起/参与 UB 数据面的一侧）。

---

## 1. 你给的五行 backbone（直接可作 Excel 第 2～6 行「调用链段」列）

| 行号(数据行) | 调用链段（建议写入 Excel 第二列） | 与时序图锚点 | 代码/模块线索（yuanrong-datasystem） |
|--------------|-----------------------------------|--------------|--------------------------------------|
| 2 | **1. client→worker1** | 读路径 **①** 控制面 | `KVClient::Get`/`GetWithLatch` → `ObjectClientImpl::Get` → `GetAvailableWorkerApi` → `ClientWorkerRemoteApi::Get` → `stub_->Get`；Worker：`WorkerOcServiceGetImpl::Get` 读帧 |
| 3 | **2. worker1 处理** | ① 之后、② 之前/之内 | `ProcessGetObjectRequest`、`TryGetObjectFromLocal`；鉴权、超时、线程池派发 |
| 4 | **3. worker1→worker2：查询元数据** | **②** | `QueryMeta`/etcd/`RawGet` 等（表上 **worker2** 可标成 Master 或「元数据依赖」若与进程模型不完全一致） |
| 5 | **4. worker1→worker3：发起数据访问请求** | **③** 控制面 | `GetObjectRemote*` / `CreateRemoteWorkerApi` 等对 **数据副本 Worker** 的 RPC |
| 6 | **5. worker3 处理并发起 URMA Write** | **④** 数据面（对入口侧常为 read/poll） | 远端侧 `UrmaWritePayload` / `urma_write`；入口侧收数、组 `GetRspPb` |

**说明**：读路径上数据面方向是 **worker3 → worker1（→ client）**；你写的「worker3 发起 URMA Write」与代码里 **远端向入口/对端写** 的语义一致，填表时可在同格或「备注」列补半句：**对端为 worker1（入口）**。

---

## 2. 建议与「第二列」配套的其它列（便于定界）

在同一 Sheet、同一 **接口=MGet** 下，每行可并列：

| 列名 | 含义 |
|------|------|
| 接口 | 固定 `MGet`（或 `Get/MGet`） |
| **调用链段** | 上表第 2 列正文 |
| 本跳传输形态 | 如 TCP(ZMQ)、etcd、Worker↔Worker RPC、UB |
| 典型 Status / 日志关键词 | 便于和 Sheet1 旧表对齐 |
| 路径类型 | `主路径-最长` / `异常-…` |
| 异常触发条件 | 仅异常行填写 |
| 代码证据 | 文件或符号 |

---

## 3. 异常行怎么接在同一 Sheet

- **不改动** 上面 1～5 的编号主链。
- 在 **某一步** 后插入行，**调用链段** 写：`1.5 异常：client→worker1 1002 无入口日志` 或 `3a 异常：etcd unavailable`。
- 或 **路径类型** 列标 `异常`，**调用链段** 仍写清 **从哪一步分叉**。

---

## 4. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-09 | 按讨论固化五行 backbone + 列建议 |
