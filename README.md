# 实验指标分析与归因评估平台

支撑AB实验分组、指标口径计算、显著性检验、归因分析与报告分发的实验评估平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/views/RiskPatrolView.vue     风险巡检工作台（专用页面 /risk_patrol）
│   ├── src/api/risk-patrol.ts           风险巡检接口封装
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/routers/risk_patrol.py  风险巡检专用路由（办理单/证据/重检/工单/复盘）
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/risk_patrol.py  风险巡检工作台领域服务
│   ├── app/services/base.py     共享服务骨架
│   ├── app/store.py          内存数据仓库与示例数据
│   └── tests/test_risk_patrol.py  风险巡检领域回归（标准库 unittest）
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8022/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5202/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8022`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 事件接入 | `event_stream` | 事件定义 | 事件编码、事件名称、属性字段 |
| 实验设计 | `exp_design` | 实验方案 | 实验编码、实验名称、分组策略 |
| 分组分配器 | `variant_assign` | 分组结果 | 分配批次、用户标识、实验编码 |
| 指标口径中心 | `metric_catalog` | 指标定义 | 指标编码、指标名称、计算口径 |
| 指标计算作业 | `metric_compute` | 计算作业 | 作业名称、指标编码、计算窗口 |
| 显著性检验 | `significance_test` | 检验结果 | 检验批次、实验编码、指标编码 |
| 归因分析器 | `attr_analysis` | 归因结果 | 归因批次、实验编码、贡献因子 |
| 人群圈选器 | `cohort_builder` | 人群包 | 人群编码、人群名称、圈选条件 |
| 报告生成器 | `report_gen` | 分析报告 | 报告编码、实验编码、报告模板 |
| 报告分发 | `report_dist` | 分发记录 | 分发批次、报告编码、接收方 |
| 窗口调度器 | `window_scheduler` | 调度计划 | 计划名称、指标编码、窗口粒度 |
| 数据时效监控 | `data_freshness` | 时效记录 | 监控对象、数据域、最新水位 |
| 指标异常检测 | `anomaly_metric` | 异常事件 | 异常编号、指标编码、基线区间 |
| 实验归档库 | `exp_archive` | 归档实验 | 实验编码、结束时间、结论摘要 |
| 样本量核对 | `sample_ratio` | 核对结果 | 核对批次、实验编码、计划比例 |
| AA预检器 | `aa_check` | AA检验 | 检验编码、实验编码、检验窗口 |
| 切片分析器 | `segment_slice` | 切片结果 | 切片批次、实验编码、切片维度 |
| 曝光日志接入 | `exposure_log` | 曝光记录 | 日志批次、实验编码、用户标识 |
| 结论评审队列 | `conclusion_review` | 评审记录 | 记录编号、实验编码、评审结论 |
| 指标查询服务 | `metric_api` | 查询接口 | 接口编码、指标编码、服务对象 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 风险巡检工作台（`/risk_patrol`）

负责人在工作台选中运行中实验发起风险巡检，服务端开具**巡检办理单**，
AA 预检器从办理单领取实际要检的实验轮次。核心规则：

- 办理单获准范围只到「实验 + 指标口径 + 检验窗口」，申请**不锁定样本版**；
  AA 领取时才按当前确认版解析实际检验版本，登记版与当前版不一致会登记版本冲突。
- 同一实验的不同指标口径、不同分配轮次/样本版本在证据看板**分别成组**，不合并。
- 样本快照（`patrol_snapshot`）分组更正确认新版后，旧版转「已过期」；
  **过期版本上的预检/重检不计入当前状态**，但保留为已办结办理单的历史依据。
- 每组人数除以总人数得到两组份额，份额差**超过 10 个百分点**才开具样本量核对工单；
  未走完核对的证据行只显示「待确认 + 实际缺项」，既无结论也不显示成零风险。
- 办理单办结与复盘材料提交时**冻结当时证据版次**；后续证据补齐、再次重检都不改写
  已办结依据与已确认复盘，复盘可随时重读保存时的证据版次并对照当前版。
- 看板选中实验触发的复查（`/recheck/board-trigger`）新办一定使用当前确认版样本。

后端测试：`make test-backend`；前端类型检查：`make typecheck-frontend`。

领域：数据工程
子方向：数据分析与数据应用
