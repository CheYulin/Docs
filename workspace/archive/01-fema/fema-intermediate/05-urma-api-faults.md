# 代码证据：URMA API 错误码 → UDMA → ubcore → Kernel 故障传播链

## 说明

本文档基于 `fault-tree-table.md` Section 2 的完整 URMA→UDMA→Kernel 故障树，
整理每个 URMA API 的错误传播路径，便于从 KVCache 症状下钻到根因层。

---

## 1. URMA 初始化类

### urma_init / urma_get_device_list / urma_get_device_by_name

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | Kernel 层 | 关键日志 |
|----------|----------|-------|---------|-----------|-----------|---------|
| `urma_init` | `URMA_EEXIST` | NA | N/A | N/A | N/A | `urma_init has been called before.` |
| `urma_init` | `URMA_FAIL` | NA | dlopen 失败 | N/A | N/A | `None of the providers registered.` / `dlopen failed: xxx` |
| `urma_get_device_list` | `nullptr` | EINVAL | 参数校验错误 | N/A | N/A | `Invalid parameter.` |
| `urma_get_device_list` | `nullptr` | ENODEV | 设备数量为0 | N/A | N/A | `urma get device list failed, device_num: 0.` |
| `urma_get_device_list` | `nullptr` | ENOMEM | 内存分配失败 | N/A | N/A | - |
| `urma_get_device_by_name` | `NULL` | EINVAL | 参数检查错误 | N/A | N/A | `Invalid dev_name.` |
| `urma_get_device_by_name` | `NULL` | ENODEV | 设备不存在 | N/A | N/A | `device list name:xxx does not match dev_name: xxx.` |

**检查工具**: `lsmod | grep udma` / `urma_admin show -a`
**恢复手段**: 部署 UB 驱动后重试

---

### urma_create_context

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | Kernel 层 | 关键日志 |
|----------|----------|-------|---------|-----------|-----------|---------|
| `urma_create_context` | `NULL` | EINVAL | 参数校验错误、空指针 | `ERR_PTR(-EINVAL)` | N/A | `Invalid parameter with err dev or ops.` |
| `urma_create_context` | `NULL` | EIO | sysfs 设备信息读取失败 | `ERR_PTR(-EPERM)` | N/A | `Failed to query eid.` |
| `urma_create_context` | `NULL` | N/A | 字符设备打开失败 | UDMA 返回值 | N/A | `Failed to open urma cdev with path xxx, dev_fd: xxx` |
| `urma_create_context` | `NULL` | N/A | udma 接口调用失败 | UDMA 返回值 | N/A | `[DRV_ERR]Failed to create urma context.` |

**检查工具**: `lsmod | grep udma` / `urma_admin show -a`
**恢复手段**: 检查驱动部署

---

### urma_query_device

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_query_device` | `URMA_EINVAL` | EINVAL | 参数校验错误 | N/A | `Invalid parameter.` |
| `urma_query_device` | `URMA_FAIL` | N/A | udma 接口调用失败 | `ubcore_query_device_attr` 返回值 | `Failed to query device attr, ret: xxx.` |

---

## 2. URMA 队列创建类 (JFC/JFR/JFS/JFCE)

### urma_create_jfc

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_create_jfc` | `NULL` | EINVAL | 参数校验错误（depth=0/超上限） | N/A | `Invalid parameter.` / `jfc cfg depth of range, depth: xxx, max_depth: xxx.` |
| `urma_create_jfc` | `NULL` | N/A | 用户态 CQ buf 分配失败 | N/A | - (返回值 14 = ENOMEM) |
| `urma_create_jfc` | `NULL` | N/A | 用户态 sw db 分配失败 | N/A | - (返回 NULL) |
| `urma_create_jfc` | `NULL` | N/A | urma_cmd_create_jfc 失败 | UDMA 返回值 | `[DRV_ERR]Failed to create jfc, dev_name: xxx, eid_idx: xxx.` |
| `urma_create_jfc` (ubcore) | `NULL` | N/A | UDMA 接口返回异常 | `ubcore_create_jfc` 返回值 | `failed to create jfc, dev_name: xxx.` |

---

### urma_create_jfr

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_create_jfr` | `NULL` | EINVAL | 参数校验错误、空指针、trans_mode 异常 | N/A | `Invalid parameter.` / `Invalid parameter, trans_mode: xxx.` |
| `urma_create_jfr` | `NULL` | EINVAL | jfr depth/sge 超上限 | N/A | `jfr cfg out of range, depth: xxx, max_depth: xxx, sge: xxx, max_sge: xxx.` |
| `urma_create_jfr` | `NULL` | ENOMEM | index queue buf 分配失败（bitmap/mmap/madvise） | N/A | - (返回值 12) |
| `urma_create_jfr` | `NULL` | EINVAL | RQ buf 分配失败（mmap/madvise） | N/A | - (返回值 22) |
| `urma_create_jfr` | `NULL` | N/A | hugepage + 普通内存都失败 | N/A | - (返回 NULL) |
| `urma_create_jfr` | `NULL` | N/A | sw_db 分配失败 | N/A | - (返回 NULL) |
| `urma_create_jfr` | `NULL` | N/A | urma_cmd_create_jfr 失败 | UDMA 返回值 | `[DRV_ERR]Failed to create jfr, dev_name: xxx, eid_idx: xxx.` |
| `urma_create_jfr` (ubcore) | `NULL` | N/A | UDMA 接口返回异常 | `ubcore_create_jfr` 返回值 | `[DRV] failed to create jfr, device: xxx.` |

---

### urma_create_jfs

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_create_jfs` | `NULL` | EINVAL | 参数校验错误、空指针 | N/A | `Invalid parameter.` |
| `urma_create_jfs` | `NULL` | EINVAL | trans_mode 非法 | N/A | `Invalid parameter, trans_mode: xxx.` |
| `urma_create_jfs` | `NULL` | EINVAL | order_type 错误 | N/A | `Invalid parameter, trans_mode: xxx, order_type: xxx.` |
| `urma_create_jfs` | `NULL` | EINVAL | depth/inline_data/sge 超出上限 | N/A | `jfs cfg out of range, depth: xxx, max_depth: xxx, inline_data: xxx, max_inline_len: xxx, sge: xxx, max_sge: xxx.` |
| `urma_create_jfs` | `NULL` | N/A | SQ buf 分配失败 | N/A | 用户态分配 SQ buf 失败 |
| `urma_create_jfs` | `NULL` | N/A | urma_cmd_create_jfs 失败 | UDMA 返回值 | `[DRV_ERR]Failed to create jfs, dev_name: xxx, eid_idx: xxx.` |
| `urma_create_jfs` | `NULL` | N/A | mmap SQ db_addr 失败 | N/A | mmap 申请 SQ db_addr 失败 |
| `urma_create_jfs` (ubcore) | `ERR_PTR(-EINVAL)` | N/A | 非法参数 | N/A | `jfs cfg is not qualified.` |
| `urma_create_jfs` (ubcore) | UDMA 返回值 | N/A | UDMA 接口失败 | N/A | `[Drv] failed to create jfs, device: xxx.` |

---

### urma_create_jfce

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_create_jfce` | `NULL` | EINVAL | 参数校验错误、空指针 | N/A | `Invalid parameter.` |
| `urma_create_jfce` | `NULL` | N/A | urma_cmd_create_jfce 失败 | UDMA 返回值 | `[DRV_ERR]Failed to create jfce, dev_name: xxx, eid_idx: xxx.` |

---

## 3. URMA 删除类

### urma_delete_context

| URMA API | 错误返回值 | errno | UDMA 层 | 关键日志 |
|----------|----------|-------|---------|---------|
| `urma_delete_context` | `URMA_EINVAL` | NA | 参数检查错误 | `Invalid parameter.` |
| `urma_delete_context` | `URMA_EAGAIN` | NA | 依赖资源未清理 | `already in use, atomic_cnt: xxx, dev_name: xxx, eid_idx: xxx.` |
| `urma_delete_context` | `URMA_FAIL` | NA | urma_cmd_delete_context 失败 | `[DRV_ERR]Delete ctx error, fd: xxx, ret: xxx, dev_name: xxx, eid_idx: xxx.` |

---

### urma_delete_jfc

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_delete_jfc` | `URMA_EINVAL` | NA | 参数检查失败、空指针 | N/A | `Invalid parameter.` |
| `urma_delete_jfc` | `URMA_EINVAL` | NA | jfc 状态异常（已 deactive） | N/A | `jfc is deactived, can not delete.` |
| `urma_delete_jfc` | UDMA 错误返回值 | NA | urma_cmd_delete_jfc 失败 | `ubcore_delete_jfc` 返回值 | `[DRV_ERR]Failed to delete jfc, dev_name: xxx, eid_idx: xxx, id: xxx, ret: xxx.` |

---

### urma_delete_jfr

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_delete_jfr` | `URMA_EINVAL` | NA | 参数检查错误、空指针 | N/A | `Invalid parameter.` |
| `urma_delete_jfr` | `URMA_EINVAL` | NA | jfr 状态异常（已 deactive） | N/A | `jfr is deactived, can not delete.` |
| `urma_delete_jfr` | UDMA 错误返回值 | NA | urma_cmd_delete_jfr 失败 | `ubcore_delete_jfr` 返回值 | `[DRV_ERR]Failed to delete jfr, dev_name: xxx, eid_idx: xxx, id: xxx, status: xxx.` |

---

### urma_delete_jfs

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_delete_jfs` | `URMA_EINVAL` | NA | 参数检查错误、空指针 | N/A | `Invalid parameter.` |
| `urma_delete_jfs` | `URMA_EINVAL` | NA | jfs 状态异常（已 deactive） | N/A | `jfs is deactived, can not delete.` |
| `urma_delete_jfs` | UDMA 错误返回值 | NA | urma_cmd_delete_jfs 失败 | `ubcore_delete_jfs` 返回值 | `[DRV_ERR]Failed to delete jfs, dev_name: xxx, eid_idx: xxx, id: xxx, ret: xxx.` |

---

### urma_delete_jfce

| URMA API | 错误返回值 | errno | UDMA 层 | 关键日志 |
|----------|----------|-------|---------|---------|
| `urma_delete_jfce` | `URMA_EINVAL` | NA | 参数检查错误 | `Invalid parameter.` |
| `urma_delete_jfce` | `URMA_FAIL` | NA | jfce 仍有引用 | N/A | `Jfce is still used by at least one jfc, refcnt: xxx.` |
| `urma_delete_jfce` | UDMA 错误返回值 | NA | - | `[DRV_ERR]Failed to delete jfce, ret: xxx.` |

---

## 4. URMA 连接与传输类

### urma_import_jfr

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_import_jfr` | `NULL` | EINVAL | 参数检查错误、空指针 | N/A | `Invalid parameter.` |
| `urma_import_jfr` | `NULL` | EINVAL | token_policy 非法 | N/A | `Token value must be set when token policy is not URMA_TOKEN_NONE.` |
| `urma_import_jfr` | `NULL` | UDMA 错误码 | urma_cmd_get_tp_list 失败 | `ubcore_get_tp_list` 返回值 | `[DRV_ERROR]Failed to get tp list, ret: xxx.` |
| `urma_import_jfr` (udma_u) | `NULL` | N/A | urma_cmd_import_jfr_ex 失败 | `ubcore_import_jfr_ex` 返回值 | `[DRV] failed to import jfr ex, dev_name: xxx, jfr_id: xxx.` |
| `urma_import_jfr` (ubcore) | `UDMA 返回值` | N/A | UDMA 接口失败 | N/A | `Failed to active tp, ret: xxx, local tpid: xxx.` |

**检查工具**: 检查 token 配置
**恢复手段**: 重试建链交换

---

### urma_import_seg

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_import_seg` | `nullptr` | EINVAL | 参数校验错误、空指针 | N/A | `Invalid parameter.` |
| `urma_import_seg` | `nullptr` | EINVAL | token 权限配置错误 | N/A | `Token value must be set when token policy is not URMA_TOKEN_NONE.` |
| `urma_import_seg` | `nullptr` | UDMA 错误码 | calloc target seg 失败 | `ubcore_import_seg` 返回值 | `[DRV] failed to import segment with va.` |

---

### urma_register_seg

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_register_seg` | `NULL` | EINVAL | 参数检查错误（空指针/seg access/token） | N/A | `Invalid parameter.` |
| `urma_register_seg` | `NULL` | EINVAL | token_id 配置错误 | N/A | `token_id must set when token_id_valid is true, or must NULL when token_id_valid is false.` |
| `urma_register_seg` | `NULL` | EINVAL | access mode 冲突 | N/A | `Local only access is not allowed to config with other accesses.` / `Write access should be config with read access.` / `Atomic access should be config with read and write access.` |
| `urma_register_seg` | `NULL` | UDMA 错误码 | ummu_grant 接口错误 | `ubcore_register_seg` 返回值 | `[DRV_ERR]Failed to register seg, dev_name: xxx, eid_idx: xxx.` |
| `urma_register_seg` | `NULL` | UDMA 错误码 | urma_cmd_register_seg 失败 | `ubcore_register_seg` 返回值 | `[DRV_ERR]register seg failed, dev_name: xxx, eid_idx: xxx.` |

---

### urma_unimport_jfr / urma_unimport_seg

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_unimport_jfr` | `URMA_EINVAL` | NA | 参数检查错误、空指针 | N/A | `Invalid parameter.` |
| `urma_unimport_jfr` | UDMA 错误返回值 | NA | urma_cmd_unimport_jfr 失败 | `ubcore_deactive_tp` 返回值 | `[DRV_ERROR]Failed to deactivate tp, ret: xxx.` |
| `urma_unimport_seg` | `URMA_EINVAL` | NA | 参数检查错误 | N/A | `Invalid parameter.` |

---

### urma_unregister_seg

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_unregister_seg` | `URMA_EINVAL` | NA | 参数检查错误、空指针 | N/A | `Invalid parameter.` |
| `urma_unregister_seg` | UDMA 异常返回值 | NA | urma_cmd_unregister_seg 失败 | `ubcore_unregister_seg` 返回值 | `[DRV_ERR]Unregister seg fail, dev_name: xxx, eid_idx: xxx, tid: xxx, ret: xxx.` |

---

### urma_get_eid_list

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_get_eid_list` | `NULL` | EINVAL | 参数校验错误、空指针 | N/A | `invalid parameter with null_ptr.` |
| `urma_get_eid_list` | `NULL` | EINVAL | eid 规格为 0 | N/A | `max eid cnt xxx is err.` |
| `urma_get_eid_list` | `NULL` | EIO | ioctl 失败 | N/A | `ioctl failed, ret: xxx, errno: xxx, cmd: xxx, kdrv_err: xxx.` |
| `urma_get_eid_list` | `NULL` | ENOMEM | OS 内存分配出错 | N/A | - |
| `urma_get_eid_list` | `NULL` | EIO | 出参 cnt 为 0 | N/A | `There is no eid in dev: xxx, max_eid_cnt: xxx.` |

---

### urma_uninit

| URMA API | 错误返回值 | UDMA 层 | 关键日志 |
|----------|----------|---------|---------|
| `urma_uninit` | `URMA_FAIL` | 调用 UDMA uninit 失败 | `Provider uninit failed xxx.` |

---

## 5. URMA 数据传输类

### urma_poll_jfc

| URMA API | 错误返回值 | errno | UDMA 层 | 关键日志 |
|----------|----------|-------|---------|---------|
| `urma_poll_jfc` | `-1` | N/A | 参数校验错误、空指针/cr_cnt 非法 | `Invalid parameter.` |
| `urma_poll_jfc` | `-1` | N/A | udma_u_poll_jfc 失败 | - |
| `urma_poll_jfc` (UDMA) | `UDMA_INTER_ERR (1)` | N/A | CQE 为空 | `JFC_EMPTY` (cqe 为 NULL) |
| `urma_poll_jfc` (UDMA) | `UDMA_INTER_ERR (2)` | N/A | CQE 解析失败 | `JFC_POLL_ERR` |

**定位**: `Failed to poll jfc` → 需重建 CQ

---

### urma_wait_jfc

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_wait_jfc` | `-1` | N/A | 参数检查错误、空指针 | N/A | `Invalid parameter.` |
| `urma_wait_jfc` | `-1` | N/A | urma_cmd_wait_jfc 失败 | N/A | - |
| `urma_wait_jfc` (ubcore) | `ERR_PTR(512)` | N/A | UDMA 中断未上报 | N/A | `Failed to wait jfce event, ret: xxx.` |

**说明**: errno 512 = UDMA 中断打断 wait，正常恢复

---

### urma_rearm_jfc

| URMA API | 错误返回值 | errno | UDMA 层 | 关键日志 |
|----------|----------|-------|---------|---------|
| `urma_rearm_jfc` | `URMA_EINVAL` | NA | 参数检查错误 | `Invalid parameter.` |
| `urma_rearm_jfc` (udma_u) | NA | N/A | 直接返回 `URMA_SUCCESS` | - |

---

### urma_post_jfs_wr / urma_write

| URMA API | 错误返回值 | errno | UDMA 层 | 关键日志 |
|----------|----------|-------|---------|---------|
| `urma_post_jfs_wr` | `URMA_EINVAL` | NA | 参数校验错误、空指针 | `Invalid parameter.` |
| `urma_post_jfs_wr` | `URMA_EINVAL` | NA | JFS post sq wr 失败 | - |
| `urma_write` | `URMA_EINVAL` | NA | 参数检查错误、空指针 | `Invalid parameter.` |
| `urma_write` | UDMA 异常返回值 | NA | UDMA 接口调用失败 | - |

**定位**: `Failed to urma write` → 降级 TCP

---

### urma_read

| URMA API | 错误返回值 | errno | UDMA 层 | 关键日志 |
|----------|----------|-------|---------|---------|
| `urma_read` | `URMA_EINVAL` | NA | 参数检查错误、空指针 | `Invalid parameter.` |
| `urma_read` | UDMA 异常返回值 | NA | UDMA 接口调用失败 | - |

---

## 6. URMA 修改类

### urma_modify_jfs

| URMA API | 错误返回值 | errno | UDMA 层 | ubcore 层 | 关键日志 |
|----------|----------|-------|---------|-----------|---------|
| `urma_modify_jfs` | `URMA_EINVAL` | NA | 参数检查错误、空指针 | N/A | `Invalid parameter.` |
| `urma_modify_jfs` | UDMA 错误返回值 | NA | urma_cmd_modify_jfs 失败 | `ubcore_modify_jfs` 返回值 | `[DRV_ERROR]Failed to modify jfs, jfs_id: xxx, ret: xxx.` |

---

## 7. URMA 日志注册类

### urma_register_log_func / urma_unregister_log_func

| URMA API | 错误返回值 | 关键日志 |
|----------|----------|---------|
| `urma_register_log_func` | `URMA_EINVAL`（参数检查错误） | `Invalid parameter.` |
| `urma_unregister_log_func` | 恒返回 `URMA_SUCCESS` | NA |

---

## 8. UDMA_INTER_ERR 错误码详解

| UDMA 错误码 | 名称 | 含义 | 处理建议 |
|------------|------|------|---------|
| 1 | `JFC_EMPTY` | CQE 为空，poll 失败 | 重建 CQ |
| 2 | `JFC_POLL_ERR` | CQE 解析失败 | 重建 CQ |
| 512 | ERR_PTR(512) | UDMA 中断打断 wait | 正常恢复，无需干预 |

---

## 9. 故障域定位汇总

| 故障域 | 错误来源 | 关键日志关键字 | 排查工具 |
|-------|---------|--------------|---------|
| **URMA 用户态** | URMA API 参数校验、状态检查 | `Invalid parameter.` / `already in use` | 代码日志 |
| **UDMA 用户态** | CQ/SQ/RQ buf 分配、mmap | ENOMEM / EINVAL | 代码日志 |
| **ubcore 内核态** | 设备操作、EID 查询 | `[DRV]` / `[DRV_ERR]` | `ubcore_log_err` |
| **UDMA 内核态** | 中断、内存分配 | - | dmesg |
| **MAMI** | 网卡设备 | - | `urma_admin show -a` |

---

## 10. 恢复机制与检查命令

| 场景 | 检查命令 | 恢复手段 |
|-----|---------|---------|
| UB 驱动未加载 | `lsmod \| grep udma` | 加载驱动：`modprobe udma` |
| UB 设备不存在 | `urma_admin show -a` | 部署 UB 驱动 |
| 驱动 so 缺失 | `ls /usr/lib64/urma/` | 重新部署驱动 |
| CQ 重建 | 代码自动重建 | `urma_create_jfc` → `urma_delete_jfc` |
| JFS 重建 | 代码自动重建 | `connection->ReCreateJfs()` |
| 连接重建 | 代码自动重连 | `TryReconnectRemoteWorker` |
| UDMA 中断异常 | `dmesg` | 正常恢复 |
