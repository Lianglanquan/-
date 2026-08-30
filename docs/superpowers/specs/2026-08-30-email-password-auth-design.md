# 邮箱密码身份认证设计

## 目标

为参与者和后台管理员建立统一的邮箱+密码身份体系，让每个 Assessment Session、回答、AI 会话分析、澄清事件和专家/管理员操作都能追溯到明确的内部用户身份。

## 约束与已确认决策

- 所有人都必须登录后才能开始新的评估。
- 登录方式为邮箱+密码；密码不以明文保存。
- 管理员只有一个角色 `ADMIN`，但允许多个管理员邮箱。
- 管理员邮箱由后端白名单控制；非白名单邮箱只能成为参与者。
- 参与者只能读取自己的评估会话；管理员可以查看全部参与者数据和 AI 分析。
- 现有小猫、逐题 Rubric、Session Orchestrator 和 Evidence Map 业务逻辑保持不变。
- Resend 只承担邮箱验证、密码重置等邮件发送，API key 只存在后端运行环境。

## 身份与数据模型

`users` 保存账号身份：随机 `id`、规范化邮箱、邮箱查找哈希、密码哈希、角色、邮箱验证时间、启用状态和时间戳。评估数据不直接以邮箱作为外键，而是通过 `assessment_sessions.user_id` 归属到内部用户 ID。

`auth_challenges` 保存邮箱验证和密码重置的一次性验证码哈希、用途、过期时间、尝试次数和消费时间。验证码不会写入日志或响应体。

`auth_sessions` 保存服务端会话 token 的哈希、用户 ID、过期时间、最后活动时间和撤销时间。浏览器只得到 `HttpOnly`、`Secure`、`SameSite=Lax` Cookie。

现有 `events`、`session_decisions`、`review_cases` 通过所属 session 间接归属参与者；新增 actor 字段时区分 `participant`、`ai`、`admin` 和 `system`，保留 AI provider/model/rubric 版本以支持审计回放。

`admin_access_logs` 记录管理员查看、导出、复核或修改数据的行为，至少包含管理员 ID、目标用户/session、动作、资源和时间。

## 认证流程

1. 注册：提交邮箱和密码；邮箱命中管理员白名单时创建为 `ADMIN`，否则创建为 `PARTICIPANT`。账号初始为未验证。
2. 邮箱验证：后端通过 Resend 发送一次性验证码；验证码单次使用、10 分钟过期并限制尝试次数。验证成功后才允许登录。
3. 登录：邮箱+密码校验成功后创建服务端会话，并轮换旧会话 token。
4. 评估：`/api/assessment/start` 和 session 读写接口都从当前会话取得 user_id，禁止前端传入或覆盖归属。
5. 恢复：登录后列出该用户未完成/已完成的 session，继续时校验 session.user_id。
6. 管理员：所有研究摘要、复核队列、导出和全量 session 查看接口要求当前用户角色为 `ADMIN`；每次读取写入访问审计。

## API 边界

- `POST /api/auth/register`
- `POST /api/auth/verify-email`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/assessment/sessions`
- `POST /api/assessment/start`
- `GET/POST /api/assessment/{session_id}` 和 `/responses`
- 现有研究接口改由管理员会话保护；旧 `X-Research-Token` 仅在迁移兼容期可作为后门关闭的 legacy 方式。

## 安全边界

- 密码使用带随机 salt 的 `scrypt` 哈希，比较使用常量时间比较。
- 邮箱统一规范化；查找使用哈希，展示时默认脱敏。
- 登录、注册、验证码和密码重置均限流；错误信息不泄露账号是否存在。
- 邮件正文不包含回答、AI 分析、风险等级或敏感评估内容，只包含验证用途和链接/验证码。
- 生产环境要求 HTTPS、Secure Cookie、明确 CORS origin、强 `AUTH_SECRET`、强 `RESEND_API_KEY`，并禁止把密钥提交到 Git。
- 删除/导出需要明确的账户级操作审计，后续可扩展账户注销与数据保留策略。

## 前端体验

- 首次访问先显示温暖的邮箱登录/注册页，文案说明“邮箱只用于确认这是你的会话”。
- 登录成功后进入欢迎页；开始评估时创建归属明确的 session。
- 顶部显示已验证邮箱的脱敏形式、继续评估和退出入口。
- 管理员登录后显示研究工作台入口；参与者看不到研究台和复核入口。
- 未登录访问评估、证据地图或后台接口时，前端回到登录页并保留目标路径。

## 验证标准

- 未登录不能开始、读取或写入评估 session。
- 两个参与者的回答和 AI 分析不会互相可见。
- 任意白名单管理员可以查看全部参与者 session；非白名单用户无法获得管理员权限。
- 验证码过期、重复使用、密码错误、会话撤销、越权读取和安全锁均有测试。
- 前端构建、后端编译、完整单元测试和最小端到端认证流程通过。
