# GitHub 发布流程

本仓库采用单人维护、CI 强制验收的流程。日常开发不直接推送 `main`。

1. 从最新 `main` 创建主题分支，在分支上完成修改。
2. 本地运行 `python -m compileall -q .` 和 `python -m pytest -q`。
3. 检查提交清单，排除凭据、数据库、账号材料、备份和运行输出。
4. 推送主题分支并创建 Pull Request。
5. 等待必需的 `test suite` 检查变绿，再合并到 `main`。

不要求第二个人批准；CI 通过是不能跳过的批准条件。

发布时，在 GitHub Actions 页面运行 `Create release`，选择 `main` 并填写新的 `vMAJOR.MINOR.PATCH`。工作流会复核 CI、创建不可变 tag 和 GitHub Release。不要手工创建、移动或覆盖公开 tag。
