# KV Client Observable Scripts

本目录存放 KV Client 可观测材料的生成脚本，避免脚本落在 `docs/`。

## 脚本

- `generate_kv_client_observability_xlsx.py`：生成 `docs/observable/workbook/kv-client/kv-client-观测-调用链与URMA-TCP.xlsx`
- `sheet1_system_presets.py`：Sheet1 URMA/OS 逐行预设与互斥规则
- `preview/build_preview.py`：生成本地静态预览 `preview/dist/index.html`

## 常用命令

```bash
python3 scripts/observable/kv-client-excel/generate_kv_client_observability_xlsx.py
python3 scripts/observable/kv-client-excel/preview/build_preview.py
```
