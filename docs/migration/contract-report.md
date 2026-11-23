# 契约报告（Plan 5 · 2026-08-29 · T6 收尾终版）

范围：FastAPI 迁移的**黄金契约**逐条对照——测试锚点（断言位置）+ 运行时实测（live_server 真实 TCP / dev server 127.0.0.1:5000，`httpx trust_env=False` 直连）。

## 契约总表

| # | 契约 | 测试锚点 | 状态 | 备注 |
|---|---|---|---|---|
| 1 | 未授权 = HTTP 200 + `{code:"unauthorized", message:"该接口需要授权才能访问，请登录后尝试", data:{}}`（**NOT 401**） | `test_contract_401.py`（153 条路由参数化，live_server 真实 TCP）+ `test_golden_contract.py`（对照 golden/401-shape.json） | ✅ | 全量回归 734 passed 内含此簇；code/message/data 与 golden 逐字段一致 |
| 2 | 公开路由直连：`/webhook` 200+success、`/favicon.ico` 204、`/default-app-icon` 200 image/png、`/healthz` 200 `{"status":"ok"}`、`/docs` 200 | `test_contract_401.py::TestPublicRoutes`（live_server） | ✅ | 实测全部 200/204 且响应正确 |
| 3 | 校验错误 = HTTP 200 + `code=validation_error`（**非 4xx**） | `test_sse_stream.py`（debug_chat 空 body）+ `test_app.py` 异常处理器 + `test_validation_messages.py` | ✅ | 实测 `POST /apps {}`（带 token）→ 200 + `code=validation_error` |
| 4 | 响应包装统一 `{code, message, data}`（success/fail/unauthorized/validation_error 同构） | `test_package/test_response.py` + `test_app.py` 异常处理器 | ✅ | 全量 734 passed |
| 5 | SSE 响应头：`Content-Type: text/event-stream` + `Cache-Control: no-cache` + `X-Accel-Buffering: no` | `test_sse_stream.py` | ✅ | 9 passed |
| 6 | SSE 事件序列（对话流）：`agent_thought → ping → agent_message → agent_end`，`error` 事件兜底 | `test_chat_runner_sse_golden.py` + `test_sse_stream.py` | ✅ | service 簇内全绿 |
| 7 | SSE 工作流流：逐节点 `workflow` 事件 → `summary` | `test_workflow*` + 运行时实测 | ✅ | 实测 8×`workflow` + `summary` |
| 8 | 路由覆盖：153 条登记路由全部注册且认证面正确 | `test_contract_401.py`（153 冒烟，live_server）+ `test_routes_registered.py` | ✅ | 环境恢复后 live 簇全绿 |
| 9 | `/default-app-icon` 二进制 PNG（长度 > 0） | `test_contract_401.py::TestPublicRoutes` | ✅ | 实测 200 + image/png |
| 10 | golden 样例文件与本实现一致 | `golden/401-shape.json`、`ping.json`、`default-app-icon.json` + `test_golden_contract.py` | ✅ | 逐字段对照通过 |
| 11 | **POST /chroma/delete 参数来源 = JSON body**（T6 补审⑳新增） | `test/app/test_chroma_delete_contract.py`（2 passed） | ✅ | T5 曾误标 Query() 造成 body→query 漂移；已改回 body 模型 + 契约测试锁定 |

## 分组说明

- **认证语义（#1/#2/#8/#9/#10）**：FastAPI 认证在 handler 参数级（`CurrentUser = Annotated[Account, Depends(get_current_user)]`），未授权统一 200+unauthorized 而非 401——旧 Flask `login_required` 语义逐条保留。153 条路由无 token 冒烟断言即此契约（live_server 真实 TCP 全绿）。
- **错误语义（#3/#4）**：异常处理器将 `CustomException→200+{code,message,data}`、`ValidationError→200+validation_error`、`RequestValidationError→200+validation_error`（T5a 契约，T6 补审确认）。
- **SSE（#5/#6/#7）**：`compact_generate_response` 包装为 `text/event-stream`，事件序列与旧同步逻辑一致。
- **请求参数来源（#11）**：POST /chroma/delete 原 Flask 读 JSON body，T5 误标 Query() 漂移——补审发现后改回 body 模型并新增契约测试（body 生效、query 不生效）。

## 运行时抽查（live_server 真实 TCP / dev server 127.0.0.1:5000）

| 检查 | 结果 |
|---|---|
| `GET /account` 无 token | 200 + `code=unauthorized` ✅ |
| `POST /apps {}` 带 token | 200 + `code=validation_error` ✅ |
| `GET /default-app-icon` | 200 + `image/png` ✅ |
| `GET /healthz` | 200 `{"status":"ok"}` ✅ |
| `POST /chroma/delete` body `{"path":...}` | 200 + success（body 契约，monkeypatch 验证）✅ |
| `POST /chroma/delete` 仅 query 参数 | 200 + validation_error/fail（query 不再生效）✅ |
| `POST /workflows/{id}/debug`（SSE） | 200 + `workflow×8 → summary` ✅ |

## 结论

**全部契约满足，无未达标项。** 全量回归 **734 passed / 0 failed**（live_server 真实 TCP 簇环境恢复后全绿）；T6 补审发现的唯一契约漂移（chroma delete body→query）已修复并加测试锁定。

