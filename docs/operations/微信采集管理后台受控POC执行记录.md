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
| 完整 pytest | Passed | 本次 Fake E2E 修复后的全量回归见提交记录；不包含真实微信数据。 |
| 只读上线前检查 | Not Executed | Pending |
| Fake 多目标、停止与断线 | Passed | 2026-07-11：隔离 E2E 双目标任务完成登录、名单、运行领取、停止、日报临时版与 390px 检查；测试库及临时账户已清理。 |
| 心跳、健康、SSE 与日报 | Passed | 2026-07-11：Fake Collector/Pipeline 运行，手动当日日报请求达到成功/部分成功并展示临时版；未启动真实微信采集。 |

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

扩容获批后仍须逐批填写 `微信采集管理后台扩容记录.md`；不得跳过 24/48 小时观察窗口。

## 7. 本次执行结论

Fake RPA 与浏览器验收已完成，但真实 POC 仍为 Not Executed。原因：当前开发数据库尚未具备管理后台任务、Worker heartbeat 与运行实例所需的迁移表；在不执行生产部署配置和数据库迁移的约束下，不创建真实任务、不触发真实微信采集，也不开始次日或扩容观察。
