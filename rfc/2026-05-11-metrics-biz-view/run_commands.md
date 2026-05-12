# Run Commands: Metrics 可视化验证

## 快速验证（本地）

```bash
# 基础生成
python3 yuanrong-datasystem-agent-workbench/scripts/metrics/metrics_biz_view.py \
  -i yuanrong-datasystem-agent-workbench/rfc/2026-05-11-metrics-biz-view/data/metrics_summary_cut.log \
  -o /tmp/worker_biz.html

# 带时间过滤（推荐）
python3 yuanrong-datasystem-agent-workbench/scripts/metrics/metrics_biz_view.py \
  -i yuanrong-datasystem-agent-workbench/rfc/2026-05-11-metrics-biz-view/data/metrics_summary_cut.log \
  -o /tmp/worker_biz.html \
  --since "10:05" -v
```

## 远程验证（xqyun-32c32g）

```bash
# 1. rsync 数据文件
rsync -av --progress \
  yuanrong-datasystem-agent-workbench/rfc/2026-05-11-metrics-biz-view/data/metrics_summary_cut.log \
  xqyun-32c32g:/tmp/

# 2. rsync Python 脚本
rsync -av --progress \
  yuanrong-datasystem-agent-workbench/scripts/metrics/metrics_biz_view.py \
  xqyun-32c32g:/tmp/metrics_biz_view.py

# 3. 远程执行
ssh xqyun-32c32g 'python3 /tmp/metrics_biz_view.py \
  -i /tmp/metrics_summary_cut.log \
  -o /tmp/worker_biz.html \
  --since "10:05" -v'

# 4. rsync 回输出
rsync -av --progress xqyun-32c32g:/tmp/worker_biz.html ./
```

## 下载文件验证

```bash
# 原始 gzip（92KB）→ 解压后（1.5MB）→ 生成 HTML（~100KB）
ls -lh /mnt/c/Users/T14S/Downloads/1c05f6c5e53a4b6ebade9c76fd3fc80c.gz
ls -lh yuanrong-datasystem-agent-workbench/rfc/2026-05-11-metrics-biz-view/data/metrics_summary_cut.log
ls -lh /tmp/worker_biz.html
```

## 在浏览器中打开

```bash
# macOS
open /tmp/worker_biz.html

# Linux (WSL)
wslview /tmp/worker_biz.html 2>/dev/null || \
  explorer.exe /tmp/worker_biz.html 2>/dev/null || \
  echo "请手动在浏览器中打开 /tmp/worker_biz.html"

# 或者用 Python HTTP server
cd /tmp && python3 -m http.server 8080
# 然后访问 http://localhost:8080/worker_biz.html
```
