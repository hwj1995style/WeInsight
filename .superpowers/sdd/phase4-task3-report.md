# 阶段四 Task 3 实施报告：异步日报请求 Repo 与生成服务

## 交付结论

阶段四 Task 3 已按正式设计和实施简报完成。新增异步日报请求领域模型、MySQL 请求仓储和日报生成编排服务，并严格保持范围边界：本任务未实现 Worker、Web 路由，也未修改既有日报分析链路。

实现文件仅为：

- `app/storage/report_request_repo.py`
- `app/services/report_generation_service.py`

测试文件仅为：

- `tests/test_report_request_repo.py`
- `tests/test_report_generation_service.py`

## 实现摘要

### 请求模型与严格校验

- 定义 `ReportType`（group/article/summary/all）、请求状态、创建请求与完整请求模型。
- manual 请求拒绝未来日期；今日请求使用当前 cutoff 并生成 provisional，历史请求生成 final/manual。
- compensation 只允许历史自然日，幂等键和次日 00:10 cutoff 均为确定值，重复补偿不会因调用时间变化而产生 payload 冲突。
- summary/all 禁止 `source_name`；字符串统一 trim、长度校验并拒绝控制字符。
- `ReportRequest` 构造时校验完整状态不变量，执行入口再次校验，未知或被运行时篡改的类型会 fail closed。

### MySQL 请求仓储

- `create_or_get` 先尝试 INSERT；仅对指定唯一键的 1062 进入幂等处理，并在新事务锁定原记录、逐项核对不可变 payload。同键异 payload 明确抛出冲突，其他数据库错误不吞。
- `claim_next` 先用短事务恢复过期任务，再在单个领取事务内通过稳定顺序和 `FOR UPDATE SKIP LOCKED` 锁定 pending 请求，并以条件 UPDATE 原子写入 running、worker、start time 和 lease。
- 过期恢复与领取拆为两个短事务。真实 MySQL 8.4 并发验证发现“恢复 UPDATE 与 SKIP LOCKED 领取放在同一事务”会形成死锁；拆分后既保留领取原子性，也消除了该锁序冲突。
- 保留正式计划的 `mark_success`、`mark_partial_success`、`mark_failed` 兼容接口；生成服务只使用新增的 owned 终态接口。
- owned 终态更新以请求 ID、running 状态、worker ID、start time、预期 lease 和 `lease > now` 共同做 CAS。任务过期并被重新领取后，旧 worker 无法覆盖新 claim。
- 所有失败摘要经既有 `sanitize_output` 脱敏并限制为 500 字；读取历史异常数据时也在边界再次净化。

### 日报生成编排

- 对外提供 `request_manual`、`ensure_compensation_request`、`execute_request`。
- 执行严格复用请求保存的 report date、trigger 和 cutoff，不以实际执行时间改写统计边界。
- all 固定按 group → article → summary 执行；summary 只读取已落库的脱敏日报聚合结果。
- 未指定来源时，通过既有日报服务公开 repo 的日报统计接口取得、排序并去重来源，再逐对象调用既有 `generate_once`；未访问 raw 数据，也未改动 Task 2 服务。
- 单对象失败与其他对象隔离：部分成功写 partial_success，全部失败写 failed，全部成功写 success；异常路径会尝试写入失败终态，不留下正常租约内的 running 请求。
- 执行前拒绝 worker 不匹配、过期租约和非法请求状态。

## TDD 与问题闭环

开发按 RED → GREEN 推进，覆盖以下关键行为：

- 请求类型、日期、来源、trigger、cutoff 和状态不变量；
- 同键同 payload 幂等、同键异 payload 冲突；
- SKIP LOCKED 领取、租约恢复、三类终态和安全错误摘要；
- 今日/历史/未来 manual、确定性补偿请求；
- all 执行顺序、请求 cutoff 保持、逐对象隔离、partial/all failed；
- 非法运行时类型 fail closed、过期租约拒绝；
- 旧 worker 在任务恢复并被新 worker 领取后的终态 CAS 拒绝。

真实 MySQL 调试中发现并修复两类并发死锁：

1. 唯一键冲突后在原 INSERT 事务内继续 `SELECT ... FOR UPDATE`；修复为回滚冲突事务后在新事务读取并核对。
2. 同一事务先全表恢复过期 running、再 SKIP LOCKED 领取；修复为独立短恢复事务加原子领取事务。

复审提出的两个 Important 项均已关闭：旧 worker 租约所有权竞争，以及非法 report type 可能造成空执行成功。复审最终结论为 Ready，Critical、Important、Minor 均无。

## 验证结果

- Task 3 定向测试：`52 passed`
- Task 3 + Task 2 日报生命周期/查询/汇总/Web 报表/入口回归：`176 passed`
- 全量测试：`1458 passed, 1 skipped`
- `python -m compileall -q app tests`：通过
- MySQL 8.4.9 临时库并发验证：通过
  - 8 线程同幂等键仅返回 1 个请求 ID；
  - 4 个并发 worker 领取 4 个互不重复请求；
  - 过期恢复、重新领取、旧 owner 拒绝、新 owner 成功；
  - success、partial_success、failed 三类终态和 500 字脱敏摘要；
  - 临时数据库在 `finally` 中清理成功。

## 风险与后续衔接

- 当前任务只提供请求仓储和生成服务，后续 Worker 必须持续沿用 owned 终态接口，不能退回仅按请求 ID 更新终态。
- Worker 的租约时长需覆盖单次生成任务，后续若引入续租，续租也必须使用同一 claim identity 做 CAS。
- Web 仅负责创建和查询请求，不应同步执行生成服务或直接查询内部表。
- 来源枚举复用既有日报统计公开接口；若后续日报服务增加稳定的来源枚举协议，可在不改变本任务执行语义的前提下替换适配层。
