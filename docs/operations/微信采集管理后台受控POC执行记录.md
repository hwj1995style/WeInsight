# 微信采集管理后台受控 POC 执行记录

当前状态：Not Executed  
决策：Pending

> 不得提前填写成功结论。真实 POC 仅限微信 PC 4.1.8.107，第一轮只允许 1 个核心群和 1 个公众号，并要求人工值守。

## 审批与环境

| 字段 | 记录 |
| --- | --- |
| 变更单号 / 批准人 | Pending |
| 执行时间 / 执行人 | Pending |
| Git 提交号 | Pending |
| 微信版本与登录账号确认 | Pending |
| 回滚负责人 | Pending |

## 自动化与 Fake RPA

| 检查 | 状态 | 安全证据摘要 |
| --- | --- | --- |
| 完整 pytest | Not Executed | Pending |
| 只读上线前检查 | Not Executed | Pending |
| Fake 多目标、停止与断线 | Not Executed | Pending |
| 心跳、健康、SSE 与日报 | Not Executed | Pending |

## 单目标真实 POC

| 链路 | run ID | UI lock / 等待 | 结果 | 停止耗时 | 本机截图路径 |
| --- | --- | --- | --- | --- | --- |
| 核心群，30 分钟 | Pending | Pending | Not Executed | Pending | Pending |
| 公众号，最小 10 分钟、每轮 1 篇 | Pending | Pending | Not Executed | Pending | Pending |

截图路径仅供本机管理员排障，不粘贴截图、不提供 Web 链接。

## 双链路与次日报表

| 检查 | 状态 | 记录 |
| --- | --- | --- |
| 群优先交错运行 1 到 2 小时 | Not Executed | Pending |
| 次日 00:10 前一自然日 final 日报 | Not Executed | Pending |
| compensation all / cutoff | Not Executed | Pending |

## Go / Watch / No-Go

决策：Pending

- 业务、运维、开发签署：Pending
- 遗留风险与观察期限：Pending
- 扩容是否获批：Pending

## 回滚记录

触发条件、回滚路径、UI lock 诊断、停止时间、恢复点和复核结果：Pending。

未得到明确 Go 和扩容批准前，保持单目标门禁，不启用自动扩容。
