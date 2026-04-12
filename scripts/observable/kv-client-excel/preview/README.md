# KV Client 定位定界 — 静态预览页

将 **`docs/observable/kv-client/puml/*.puml`**、**`docs/reliability/00-kv-client-visible-status-codes.md`** 与 **`docs/observable/workbook/kv-client/kv-client-观测-调用链与URMA-TCP.xlsx` 第一工作表** 打成一页 HTML，便于浏览器预览或截屏进 Word。

## 依赖

- **Java**（用于 PlantUML）
- **Python 3** + `markdown`、`openpyxl`（见 `requirements-preview.txt`）

建议使用虚拟环境：

```bash
cd scripts/observable/kv-client-excel/preview
python3 -m venv .venv
.venv/bin/pip install -r requirements-preview.txt
```

## 生成

在 **`vibe-coding-files` 仓库根目录**（或任意目录，脚本内为绝对逻辑路径）执行：

```bash
python3 scripts/observable/kv-client-excel/preview/build_preview.py
```

- **PlantUML**：未设置 `PLANTUML_JAR` 时，会依次尝试环境变量、`/tmp/plantuml.jar`、本目录 `.cache/plantuml.jar`（不存在则自动下载）。
- **Excel**：路径为 `docs/observable/workbook/kv-client/kv-client-观测-调用链与URMA-TCP.xlsx`；若缺失，页面中会提示，可先运行 `scripts/observable/kv-client-excel/generate_kv_client_observability_xlsx.py` 生成。

## 打开预览

生成结果在 **`dist/index.html`**（`dist/` 已列入 `.gitignore`）。用浏览器打开：

```text
file:///…/vibe-coding-files/scripts/observable/kv-client-excel/preview/dist/index.html
```

或用本地静态服务器（避免个别浏览器对 `file://` 的限制）：

```bash
cd scripts/observable/kv-client-excel/preview/dist && python3 -m http.server 8765
# 访问 http://127.0.0.1:8765/
```
