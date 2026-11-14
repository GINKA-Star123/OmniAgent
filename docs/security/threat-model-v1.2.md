# V1.2 最小威胁模型与第五批执行边界

更新日期：2026-10-27。状态：第五批设计与验收目标，不是测试通过证明。

## 目标与非目标

目标一：可信主体只能访问自己的用户面资源，原始敏感问答不能绕过 Memory 批准正文进入持久记忆。
目标二：真实生成失败不能以用户原文冒充助手成功输出。
后续安全主题：第八批 Rust 组件审查上下文来源与用途，不建设全语义安全判官。
本批不开发账号平台、前端、全局 exactly-once、持久任务恢复或媒体解析沙箱。
按用户要求，本批不考虑 Live2D/Presence 契约修复。

## 资产与信任边界

资产：长期记忆、会话/checkpoint、通话、私有音频、用户上传图片、输出标识、Provider 凭证、管理凭证、审计。
不可信输入：用户文本、图像/OCR 文本、检索文本、请求 user_id/call_id/session_id、客户端 Header、任意 metadata、Provider 错误正文。
可信配置：部署端维护的 Token 摘要到 principal 映射、管理员凭证、已锁定且审查过的依赖。
可信代码：服务进程内部签发逻辑；不承诺抵御进程被任意代码执行后伪造批准。
Provider 与向量数据库是外部信任边界，批准事实仍可能发送给嵌入 Provider。

## 身份与资源矩阵

| 资源/入口 | 创建/使用主体 | 读取/修改/清理要求 | 缺失归属时 |
| --- | --- | --- | --- |
| chat/vision/multimodal/session open | Bearer principal，或显式 local-dev 固定主体 | body/Form user_id 必须匹配 | 拒绝，不认领旧用户 |
| session/thread | principal + logical session 派生后端 ID | 同用户命名空间，Redis owner 继续复核 | 旧命名空间不自动恢复 |
| memory | user + agent 双作用域 | API path 匹配 principal，单条记录 owner 必须完整 | not_found |
| call | start 写入认证主体 | state/end/interrupt/turn 在任何变更前检查 owner | 统一 404 |
| image | 认证上传即消费 | 不开放用户任意路径读取/下载/重用 | 不开放复用入口 |
| audio | Dispatcher 注册随机私有副本 | Bearer owner + Path containment + 文件存在 | 统一 404 |
| output | Dispatcher 登记 owner | 不开放全局用户输出查询；未来查询必须检查 owner | 不认领 |
| task/知识管理/图库重建 | admin | 全部管理面 | 拒绝普通用户 |
| 全局状态/控制/本机硬件 | admin | 普通 call interrupt 不触发全局硬件打断 | 拒绝普通用户 |
| cloud-files/对象管理 | admin | local 私有下载；外部桶需私有 ACL | 不保留公开挂载 |

管理员不是普通用户代理身份。CORS、IP、限流桶、X-User-ID 不构成用户认证。关闭公开文档与静态挂载，未知路由默认管理面。

## Memory 批准载荷契约

批准前：当前请求内可以使用原始问答做 policy 和检索，禁止将其复制到后台任务、审计或写入 metadata。
批准后：不可变载荷仅含 user/agent、过滤正文、受控分类/重要性/来源、会话/回合摘要引用和时间。
签名：同进程 HMAC 绑定正文和作用域；最终适配器验签并再次检查正文。
持久化：Mem0 infer=False，仅一条 user 正文，禁止 assistant 原文、prompt、自由 metadata、图抽取。
编辑/合并：先验证实际记录归属，再过滤新正文；metadata 重建白名单，不合并旧 hint/reason。
失败：不合法返回、SDK 失败字典、异常均不算 stored；不确定外部结果不自动重试。
审计：仅固定状态码，不保存候选、policy reason、原始用户名或 Provider 错误。

## 生成故障契约

真实 Provider 失败抛出 generation_unavailable，不能使用用户输入作为 fallback。
失败不得创建本轮成功 AIMessage、长期记忆、TTS 音频或成功输出历史。
输入 checkpoint 或已开始的外部调用可能存在，不承诺回滚全部状态。
Mock 必须标识 llm_inference=mock；抽取式事实回答标识 skipped_extractive，不混为真实模型生成。

## 部署、迁移与回滚

生产要求 HTTPS、bearer、Redis、私有共享音频卷、voice store fail closed、关闭本机播放。
local-dev 仅回环、单进程、固定用户，不能复制为云默认。
先 drain 旧后台任务并备份，再统一替换 API Worker；不允许新旧自由抽取链路并存。
旧无 owner 记忆/音频不能自动认领；历史公开桶、日志和审计需单独治理。
回滚采用关闭受影响能力/维护模式，不恢复匿名自报身份、公开文件或原文回显。

## 验收证据

必须保存单元、Memory 适配器载荷捕获、正反 contrast、HTTP owner contract、既有 smoke 回归结果。
分别记录本地模拟/Redis adapter/真实 Redis；真实 Redis skip 不等于通过。
离线 Mem0 SDK 无推断分支不等于真实向量库集成通过。
未运行的测试标为未运行，不能用静态审阅或 mock 结果替代真实外部覆盖。

## 残余风险与后续责任

第六批：generation/fence、超时线程迟到、隐式 checkpoint、删除/禁用屏障、偏好跨进程一致性。
第七批：输出消费/播放协议、Presence 服务端时间与受控主动性；Live2D 本轮延期。
第八批：Rust 来源/用途审查，不宣称解决全部间接 Prompt Injection。
第九批：私有资源索引/文件 TTL、清理、配额、持久队列和恢复；内存索引不跨重启。
本批敏感过滤不覆盖所有秘密/隐私表达，媒体解析仍在 Python 进程，外部 Provider 需独立评估。

## 2026-11-14 静态复核补充

GIF 已接入 ImageStore、VisionService、VisionGraph 与三个 HTTP 上传入口：
格式与后缀一致校验、有界逐帧检查、最多六帧的有序多图请求，拒绝回退成首帧成功。
Mock 明确标记未做真实动画理解；GIF 不产生视觉长期记忆提示，但用户自己表达的稳定文本偏好仍可独立审核。
GIF 拒绝超过帧数、像素、时长、上传体积及编码后载荷预算的输入；它不是进程沙箱。

Memory 共享状态错误先传播，普通可选检索故障才降级。审计与异步历史不持久化候选正文和异常原文。
资源 owner 采用批量冲突检查后原子登记；音频复制或归属登记失败时清理本轮副本。
这不保证进程被强制终止或 Redis 提交结果不确定时的跨系统原子性，恢复与过期清理仍待后续批次。

Mem0 的 `infer=False` 仍调用 embedding，并保留 SDK 历史/实体等副作用。
已增加已确认 logger `mem0.memory.main` 的过滤器；它不是全局日志脱敏。
`MEM0_TELEMETRY=false` 必须在 SDK 首次导入前进入真实进程环境；模板存在该项不等于本地进程已经生效。

本轮未运行单元、合同、对照、回归、真实 Redis、Provider 或容器测试。源码落地与验收通过分别记录。
