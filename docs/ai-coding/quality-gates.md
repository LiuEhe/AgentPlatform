# 质量门禁

先运行与改动相关的检查，报告实际结果。下面说明现有检查能证明什么，以及哪些仍需真实环境验收。

## 常用命令

| 范围 | 执行目录与命令 | 前提 |
| --- | --- | --- |
| 后端静态检查 | `backend/`：`uv run ruff check app scripts tests` | 已安装开发依赖 |
| 后端测试 | `backend/`：`uv run pytest` | 数据库用例须显式设置专用 `TEST_DATABASE_URL`，见[数据库测试](../database.md#测试与维护) |
| 前端回归 | `frontend/`：`node --test` | 使用 Node 内置测试及已有 Vue/TypeScript |
| 前端类型与构建 | `frontend/`：`pnpm build` | 脚本为 `vue-tsc -b && vite build` |
| 纯文档 | 核对链接、路径、命令、规则与实现的一致性 | 无需运行无关业务测试 |

依赖锁为 `backend/uv.lock` 和 `frontend/pnpm-lock.yaml`。准备开发依赖使用 `uv sync --locked --group dev`，前端使用冻结锁文件安装；依赖变更仍需审批。当前没有独立前端 lint/test 脚本、浏览器端到端测试框架或依赖漏洞扫描。

## CI 实际运行什么

[ci.yml](../../.github/workflows/ci.yml) 在 Pull Request 和推送到 main/dev 时执行：

- 后端：Python 3.12、3.13，专用 PostgreSQL 18 测试库，Ruff 和 pytest。
- 前端：冻结锁文件安装，以下 9 个 Node 测试文件，再运行生产构建。

```powershell
node --test src/features/conversation-assistant/useConversation.test.cjs src/features/auth/useAuth.test.cjs src/features/auth/appLifecycle.test.cjs src/api/auth.test.cjs src/components/ConfirmDialog.test.cjs src/components/confirmationFlows.test.cjs src/features/auth/AccountMenu.test.cjs src/features/auth/UserManagement.test.cjs src/features/auth/ProfileForm.test.cjs
```

确认框回归覆盖取消/焦点恢复、忙碌与重复确认、删除目标、账号身份变化、过时停止提示和未保存资料的离开决策；资料表单覆盖性别/生日选择、日期有效性及跨日上限。CI 尚未运行其余头像和会话状态模块独立测试；本地 `node --test` 可运行全部现有前端回归。可按文件路径单独运行相关用例。

## 已有覆盖与验收边界

| 领域 | 现有检查 | 仍需另行验收 |
| --- | --- | --- |
| 会话与记忆 | 真实编译图、意图/补参、材料引用、摘要预算、父子调用、幂等、分页；失败不推进成功位置 | 真实模型识别和摘要质量、上下文上限、账户额度 |
| 制度审核 | DOCX 解析、双模式、分组顺序、共享额度、取消、报告与 HTTP 入口；模型/检索使用替身 | 真实模型准确性、RAGFlow 网络、生产吞吐 |
| 数据库与删除 | 专用库随机 schema、官方 setup/checkpointer、事务、归属、回滚、重启与清理重试；文件用临时目录 | 生产备份恢复与容量 |
| 账号与头像 | 登录/撤销、强制改密、CSRF/来源/身份上下文、资料差量、图片处理、状态未知后的恢复 | 真实多标签页、离线退出、浏览器缓存与身份切换 |
| SSE | 标准帧、分块、快照、重连不重跑、多订阅、取消唤醒、临时容量 | 真实模型分块时序与代理及时转发 |
| 前端交互 | 会话切换、草稿隔离、迟到响应、取消与删除重试；资料/头像组件用受控宿主 | 输入法、键盘、手机布局、Canvas、原生 dialog 和实际像素效果 |
| Word 导出 | 输入/输出限制、内容样式、并发、取消、进程回收及包内 Pandoc 集成 | 目标 Word/WPS 的分页、字体替代、复杂表格 |

发布验收必须实际运行 `tests/test_document_export_integration.py`，不能把缺依赖跳过算作通过。受控浏览器响应不代表后端、模型、知识库或 Word 转换已联调；原型截图与正式页面截图也须分开说明。

`tests/test_user_profile_sql.py` 静态检查新环境初始化 SQL 的资料字段类型、可空性、无默认值、约束表达式及结构版本；不依赖旧库增量迁移脚本。项目仅支持当前结构的新库初始化，未提供资料字段增量迁移；静态检查不替代真实数据库验收。

## 交付要求

新功能检查用户场景，修复问题尽可能先建立失败复现；验证可观察行为、边界和错误路径，不用测试数量替代覆盖质量。失败应调查，不删有效测试、不降断言、不改数据来凑通过。

完成前检查 diff：只保留本任务必要改动，核对密钥、配置、锁文件、数据库资产和生成物，不能覆盖用户已有工作。汇报分清已实现、已运行及结果、未运行和未验收，不能将替身通过或未执行写成真实环境验收通过。
