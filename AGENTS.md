# Agent 说明

本仓库 **`vibe-coding-files`** 与 **`yuanrong-datasystem`** 配对使用：前者承载**脚本 + 文档 + 计划**，后者以**源码与 `build.sh`** 为主。

请先阅读：

1. [`docs/agent/README.md`](docs/agent/README.md)  
2. [`docs/agent/scripts-map.md`](docs/agent/scripts-map.md)（`scripts/{build,index,perf,verify}/` 何时用哪个）  
3. [`docs/verification/手动验证确认指南.md`](docs/verification/手动验证确认指南.md)（逐步验收）  
4. [`docs/verification/cmake-non-bazel.md`](docs/verification/cmake-non-bazel.md)  
5. [`docs/verification/构建产物目录与可复现工作流.md`](docs/verification/构建产物目录与可复现工作流.md)（第三方缓存与 `output`/`build` 结构）  
6. [`plans/agent开发载体_vibe与yuanrong分工.plan.md`](plans/agent开发载体_vibe与yuanrong分工.plan.md)  

执行本仓库脚本时，若未与 `yuanrong-datasystem` 同级放置，请设置 `DATASYSTEM_ROOT`。
