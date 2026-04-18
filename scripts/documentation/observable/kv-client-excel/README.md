# KV Client Observable Scripts

本目录存放 KV Client 可观测材料的生成脚本，避免脚本落在 `docs/`。

## 脚本

- `generate_kv_client_observability_xlsx.py`：生成 `docs/observable/workbook/kv-client-观测-调用链与URMA-TCP.xlsx`
- `sheet1_system_presets.py`：Sheet1 URMA/OS 逐行预设与互斥规则
- `preview/build_preview.py`：生成本地静态预览 `preview/dist/index.html`

## 常用命令

```bash
# 生成 xlsx
./ops docs.kv_observability_xlsx
# 或
python3 scripts/documentation/observable/kv-client-excel/generate_kv_client_observability_xlsx.py

# 生成静态预览
./ops docs.kv_observability_preview
# 或
python3 scripts/documentation/observable/kv-client-excel/preview/build_preview.py
```

## 对外文档

- [`docs/observable/workbook/README.md`](../../../../docs/observable/workbook/README.md)：工作簿与 Sheet 对照
- [`docs/observable/03-fault-mode-library.md`](../../../../docs/observable/03-fault-mode-library.md)：FM 清单（与 `sheet1_system_presets.py` 编号对齐）
