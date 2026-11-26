"""风险巡检工作台领域服务。

数据链路位置：实验运行期的风险治理层。运营负责人在工作台选中运行中实验并发起
风险巡检，服务端开具「巡检办理单」；AA 预检器从办理单领取实际要检的实验轮次并
执行一次实际重检；样本量证据不足时开具样本量核对工单；运营复盘消费同轮已确认的
检验与样本数据。

核心不变量：
1. 办理单只获准到「实验 + 指标口径 + 窗口」，提交申请不锁定样本版，领取时才按
   当前确认版解析，版本冲突会显式登记；
2. 同一实验的不同指标口径、不同分配轮次分别列证据，不合并；
3. 已过期样本版本上的预检/重检不计入当前状态，但仍作为已办结办理单的历史依据；
4. 样本量核对未走完前，证据行只呈现「待确认 + 实际缺项」，既无结论也不显示零风险；
5. 办理单办结、复盘材料提交时冻结当时证据版次；后续证据补齐或重检不改写已确认材料。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 两组份额相差超过该阈值（10 个百分点）时，复查必须开具样本量核对工单。
RATIO_WORK_ORDER_THRESHOLD = 0.10

# 办理单状态。
TICKET_STATUSES = ["待领取", "检验中", "待确认", "已办结"]
# AA 重检结论。
RUN_RESULTS = ["待重检", "无显著差异", "检出差异"]
# 样本量核对工单状态。
WORK_ORDER_STATUSES = ["待核对", "已核对"]
# 样本证据快照状态。
SNAPSHOT_STATUSES = ["已确认", "已过期"]
# 复盘材料状态。
RETRO_STATUSES = ["已提交", "已确认"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(r.get("id", 0)) for r in rows), default=0) + 1


class RiskPatrolService(BaseModuleService):
    """巡检办理单资源：沿用通用列表/详情接口，业务流转走专用路由。"""

    MODULE = "risk_patrol"
    ENTITY = "巡检办理单"
    OPERATION_TERM = "巡检"
    LIST_FIELDS = [
        "工单编号", "实验编码", "指标编码", "口径版本", "检验窗口",
        "分配轮次", "样本版本", "工单状态", "申请时间",
    ]
    REQUIRED_FIELDS = ["实验编码", "指标编码", "检验窗口"]
    STATUS_ORDER = TICKET_STATUSES
    ACTION_RULES: dict[str, str] = {}
    NEGATIVE_ACTIONS: list[str] = []

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """禁用通用登记：巡检办理单必须经 submit_ticket 走完整校验与证据装配。"""
        return None, ["巡检办理单不支持通用登记，请使用 POST /api/risk-patrol/tickets"]

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """禁用通用动作：领取/重检/办结/核对均有专用领域方法与不变量校验。"""
        return None, "巡检办理单不支持通用动作，请使用风险巡检工作台专用接口"

    # ------------------------------------------------------------------ #
    # 样本证据快照（版本）
    # ------------------------------------------------------------------ #

    def list_snapshots(self, exp_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows("patrol_snapshot")
        if exp_code:
            rows = [r for r in rows if r.get("实验编码") == exp_code]
        return rows

    def current_snapshot(self, exp_code: str) -> dict[str, Any] | None:
        """当前确认版样本快照：只有「已确认」才算当前，过期版不计入当前状态。"""
        return next(
            (r for r in store.rows("patrol_snapshot")
             if r.get("实验编码") == exp_code and r.get("status") == "已确认"),
            None,
        )

    def confirm_snapshot(
        self,
        exp_code: str,
        alloc_round: str,
        ctrl_count: int,
        treat_count: int,
    ) -> dict[str, Any]:
        """确认一版样本证据（分组更正后调用）：旧确认版转过期，新版本成为当前版。

        两组人数各自除以总人数得到份额；份额差随快照保存，供后续工单阈值判定。
        """
        if ctrl_count < 0 or treat_count < 0 or ctrl_count + treat_count <= 0:
            return {"ok": False, "message": "两组人数必须为非负整数且总人数大于 0"}
        previous = self.current_snapshot(exp_code)
        if previous is not None:
            previous["status"] = "已过期"
            previous["pending"] = False
        total = ctrl_count + treat_count
        ctrl_share = round(ctrl_count / total, 4)
        treat_share = round(treat_count / total, 4)
        version_no = sum(1 for r in store.rows("patrol_snapshot") if r.get("实验编码") == exp_code) + 1
        snapshot = {
            "id": _next_id(store.rows("patrol_snapshot")),
            "status": "已确认",
            "pending": False,
            "abnormal": False,
            "样本版本": f"{exp_code}-V{version_no}",
            "实验编码": exp_code,
            "分配轮次": alloc_round,
            "对照组人数": ctrl_count,
            "实验组人数": treat_count,
            "总人数": total,
            "对照组份额": ctrl_share,
            "实验组份额": treat_share,
            "份额差": round(abs(ctrl_share - treat_share), 4),
            "确认时间": _now(),
        }
        store.rows("patrol_snapshot").append(snapshot)
        conflict_tickets = [
            t for t in store.rows(self.MODULE)
            if t.get("实验编码") == exp_code
            and t.get("工单状态") == "待领取"
            and t.get("登记样本版本")
            and t.get("登记样本版本") != snapshot["样本版本"]
        ]
        for ticket in conflict_tickets:
            ticket["版本冲突"] = True
            ticket["冲突说明"] = (
                f"申请登记 {ticket['登记样本版本']}，当前确认版已更新为 {snapshot['样本版本']}"
            )
        return {
            "ok": True,
            "message": f"样本快照 {snapshot['样本版本']} 已确认（{ctrl_count}:{treat_count}）",
            "snapshot": snapshot,
            "冲突办理单数": len(conflict_tickets),
        }

    # ------------------------------------------------------------------ #
    # 运行实验与口径/轮次工作台
    # ------------------------------------------------------------------ #

    def running_experiments(self) -> list[dict[str, Any]]:
        """工作台可选的运行中实验，并对照当前口径版本与当前样本证据。"""
        result = []
        for exp in store.rows("exp_design"):
            if exp.get("status") != "运行中":
                continue
            exp_code = str(exp.get("实验编码", ""))
            snapshot = self.current_snapshot(exp_code)
            result.append({
                "实验编码": exp_code,
                "实验名称": exp.get("实验名称", ""),
                "假设指标": exp.get("假设指标", ""),
                "当前样本版本": snapshot.get("样本版本") if snapshot else None,
                "当前分配轮次": snapshot.get("分配轮次") if snapshot else None,
                "待处理巡检数": sum(
                    1 for t in store.rows(self.MODULE)
                    if t.get("实验编码") == exp_code and t.get("工单状态") != "已办结"
                ),
            })
        return result

    def _metric_calibers(self, metric_codes: list[str]) -> dict[str, dict[str, Any]]:
        """对照指标口径中心的当前生效口径（口径版本随证据一起保存）。"""
        calibers: dict[str, dict[str, Any]] = {}
        for metric in store.rows("metric_catalog"):
            code = str(metric.get("指标编码", ""))
            if code in metric_codes and metric.get("status") == "已生效":
                calibers[code] = {
                    "指标编码": code,
                    "指标名称": metric.get("指标名称", ""),
                    "口径版本": metric.get("口径版本", ""),
                    "计算口径": metric.get("计算口径", ""),
                    "聚合窗口": metric.get("聚合窗口", ""),
                }
        return calibers

    # ------------------------------------------------------------------ #
    # 巡检办理单
    # ------------------------------------------------------------------ #

    def submit_ticket(
        self,
        exp_code: str,
        metric_code: str,
        window: str,
        remark: str = "",
    ) -> dict[str, Any]:
        """运营负责人提交运行指标及窗口复查。

        获准范围只到「实验 + 指标 + 窗口」；申请不锁定样本版，只登记提交时的当前
        确认版作为初算依据，AA 领取时再解析实际检验版本。
        """
        exp = next(
            (r for r in store.rows("exp_design")
             if r.get("实验编码") == exp_code and r.get("status") == "运行中"),
            None,
        )
        if exp is None:
            return {"ok": False, "message": f"实验 {exp_code} 不在运行中，不能发起巡检"}
        caliber = self._metric_calibers([metric_code]).get(metric_code)
        if caliber is None:
            return {"ok": False, "message": f"指标口径 {metric_code} 不存在或未生效"}
        snapshot = self.current_snapshot(exp_code)
        rows = store.rows(self.MODULE)
        ticket = {
            "id": _next_id(rows),
            "status": "待领取",
            "pending": True,
            "abnormal": False,
            "工单编号": f"PT-{exp_code}-{_next_id(rows):04d}",
            "实验编码": exp_code,
            "指标编码": metric_code,
            "口径版本": caliber["口径版本"],
            "检验窗口": window,
            "分配轮次": snapshot.get("分配轮次") if snapshot else None,
            "样本版本": None,
            "登记样本版本": snapshot.get("样本版本") if snapshot else None,
            "工单状态": "待领取",
            "申请时间": _now(),
            "申请备注": remark,
            "版本冲突": False,
            "冲突说明": "",
            "领取时间": None,
            "重检记录ID": None,
            "初次重算记录ID": None,
            "初次核对工单编号": None,
            "工单依据": None,
            "办结时间": None,
            "冻结证据": None,
        }
        rows.append(ticket)
        return {
            "ok": True,
            "message": (
                f"巡检办理单 {ticket['工单编号']} 已开具（范围：{metric_code}/{window}，"
                f"未锁定样本版）"
            ),
            "ticket": ticket,
        }

    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        return store.find(self.MODULE, ticket_id)

    def list_claimable(self) -> list[dict[str, Any]]:
        """AA 预检器可领取的办理单：待领取且尚未被领取。"""
        return [
            t for t in store.rows(self.MODULE) if t.get("工单状态") == "待领取"
        ]

    def claim_ticket(self, ticket_id: int) -> dict[str, Any]:
        """AA 预检器领取办理单：解析实际要检的实验轮次与样本版本。

        若申请登记版与当前确认版不一致，登记版本冲突；登记的旧版仍可用于重算
        初次风险（旧版 6:4 份额差超 10pp 会开具旧版核对工单），但本次实际检验
        一律按当前确认版执行（新办一定用当前版）。
        """
        ticket = store.find(self.MODULE, ticket_id)
        if ticket is None:
            return {"ok": False, "message": "巡检办理单不存在"}
        if ticket.get("工单状态") != "待领取":
            return {"ok": False, "message": "该办理单已被领取或已办结，不能重复领取"}
        exp_code = str(ticket.get("实验编码", ""))
        snapshot = self.current_snapshot(exp_code)
        if snapshot is None:
            return {"ok": False, "message": f"实验 {exp_code} 无已确认样本证据，不能领取检验"}
        registered = ticket.get("登记样本版本")
        conflict = bool(registered and registered != snapshot["样本版本"])
        initial_run = None
        initial_work_order = None
        if conflict:
            # 登记旧版仍用于初次风险重算：固化旧版分组，超阈值开具旧版核对工单。
            old_snapshot = next(
                (r for r in store.rows("patrol_snapshot") if r.get("样本版本") == registered),
                None,
            )
            if old_snapshot is not None:
                initial_work_order = self._ensure_work_order(old_snapshot, ticket["工单编号"])
                initial_run = self._append_run(
                    ticket, old_snapshot, "初次风险重算", "待重检", None, initial_work_order,
                )
                ticket["初次重算记录ID"] = initial_run["id"]
                ticket["初次核对工单编号"] = (
                    initial_work_order["工单编号"] if initial_work_order else None
                )
        ticket["样本版本"] = snapshot["样本版本"]
        ticket["分配轮次"] = snapshot["分配轮次"]
        ticket["工单状态"] = "检验中"
        ticket["status"] = "检验中"
        ticket["领取时间"] = _now()
        ticket["版本冲突"] = conflict
        if conflict:
            ticket["冲突说明"] = (
                f"申请登记 {registered}，领取时当前确认版为 {snapshot['样本版本']}；"
                f"旧版已做初次风险重算（{initial_run['开单结果'] if initial_run else '无证据'}），"
                "本次实际检验按当前确认版执行"
            )
        conflict_note = (
            f"，检测到版本冲突（{registered} → {snapshot['样本版本']}）" if conflict else ""
        )
        message = (
            f"办理单 {ticket['工单编号']} 已领取，实际检验轮次 {snapshot['分配轮次']}"
            + conflict_note
        )
        if initial_run is not None:
            message += f"；旧版 {registered} 初次风险重算：{initial_run['开单结果']}"
        return {
            "ok": True,
            "message": message,
            "ticket": ticket,
            "snapshot": snapshot,
            "版本冲突": conflict,
            "初次风险重算": initial_run,
            "初次核对工单": initial_work_order,
        }

    # ------------------------------------------------------------------ #
    # AA 实际重检
    # ------------------------------------------------------------------ #

    def list_runs(self, exp_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows("patrol_aa_run")
        if exp_code:
            rows = [r for r in rows if r.get("实验编码") == exp_code]
        return rows

    def _open_work_order_for(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        return next(
            (w for w in store.rows("patrol_work_order")
             if w.get("样本版本") == snapshot.get("样本版本") and w.get("status") == "待核对"),
            None,
        )

    def _ensure_work_order(self, snapshot: dict[str, Any], source_ticket: str) -> dict[str, Any] | None:
        """份额差超 10pp 时开具（或复用）样本量核对工单，返回工单；未超阈值返回 None。"""
        if float(snapshot["份额差"]) <= RATIO_WORK_ORDER_THRESHOLD:
            return None
        work_order = self._open_work_order_for(snapshot)
        if work_order is not None:
            return work_order
        wo_rows = store.rows("patrol_work_order")
        work_order = {
            "id": _next_id(wo_rows),
            "status": "待核对",
            "pending": True,
            "abnormal": True,
            "工单编号": f"WO-{snapshot['样本版本']}",
            "实验编码": snapshot.get("实验编码"),
            "分配轮次": snapshot.get("分配轮次"),
            "样本版本": snapshot.get("样本版本"),
            "对照组份额": snapshot.get("对照组份额"),
            "实验组份额": snapshot.get("实验组份额"),
            "份额差": snapshot.get("份额差"),
            "阈值": RATIO_WORK_ORDER_THRESHOLD,
            "来源办理单": source_ticket,
            "开单时间": _now(),
            "核对时间": None,
            "核对说明": "",
        }
        wo_rows.append(work_order)
        return work_order

    def _append_run(self, ticket: dict[str, Any], snapshot: dict[str, Any],
                    run_type: str, result: str, p_value: float | None,
                    work_order: dict[str, Any] | None) -> dict[str, Any]:
        """登记一条检验记录：实际重检或初次风险重算，均固化适用口径与实际分组。"""
        run_rows = store.rows("patrol_aa_run")
        run = {
            "id": _next_id(run_rows),
            "status": result or "待重检",
            "pending": result == "检出差异",
            "abnormal": result == "检出差异",
            "重检编号": f"AR-{ticket['工单编号']}-{run_type}",
            "重检类型": run_type,
            "来源办理单": ticket["工单编号"],
            "实验编码": ticket.get("实验编码"),
            "指标编码": ticket.get("指标编码"),
            "口径版本": ticket.get("口径版本"),
            "检验窗口": ticket.get("检验窗口"),
            "分配轮次": snapshot.get("分配轮次"),
            "样本版本": snapshot.get("样本版本"),
            "样本快照状态": snapshot.get("status"),
            "对照组人数": snapshot.get("对照组人数"),
            "实验组人数": snapshot.get("实验组人数"),
            "对照组份额": snapshot.get("对照组份额"),
            "实验组份额": snapshot.get("实验组份额"),
            "份额差": snapshot.get("份额差"),
            "检验结论": result,
            "P值": "" if p_value is None else str(p_value),
            "开单结果": (
                f"已开具核对工单 {work_order['工单编号']}" if work_order
                else f"份额差 {snapshot.get('份额差')} 未超 10pp，无需核对"
            ),
            "核对工单编号": work_order.get("工单编号") if work_order else None,
            "检验时间": _now(),
        }
        run_rows.append(run)
        return run

    def execute_recheck(
        self,
        ticket_id: int,
        result: str,
        p_value: float | None = None,
    ) -> dict[str, Any]:
        """对已领取办理单执行一次实际 AA 重检，并记录适用口径与分组。

        一次领取只允许一次实际重检；按领取时解析的样本版本读取两组实际人数，
        份额差超过 10 个百分点时开具（或复用）样本量核对工单。
        """
        ticket = store.find(self.MODULE, ticket_id)
        if ticket is None:
            return {"ok": False, "message": "巡检办理单不存在"}
        if ticket.get("工单状态") not in ("检验中", "待确认"):
            return {"ok": False, "message": "仅已领取、检验中的办理单可执行重检"}
        if ticket.get("重检记录ID"):
            return {"ok": False, "message": "该办理单已完成实际重检，不能重复检验"}
        if result not in RUN_RESULTS[1:]:
            return {"ok": False, "message": f"重检结论必须为 {'/'.join(RUN_RESULTS[1:])}"}
        snapshot = next(
            (r for r in store.rows("patrol_snapshot")
             if r.get("样本版本") == ticket.get("样本版本")),
            None,
        )
        if snapshot is None:
            return {"ok": False, "message": "适用样本版本证据不存在，无法记录实际分组"}
        work_order = self._ensure_work_order(snapshot, ticket["工单编号"])
        run = self._append_run(ticket, snapshot, "实际重检", result, p_value, work_order)
        ticket["重检记录ID"] = run["id"]
        ticket["工单状态"] = "待确认"
        ticket["status"] = "待确认"
        ticket["pending"] = True
        ticket["工单依据"] = self._ticket_basis(ticket)
        message = (
            f"实际重检已记录（{run['重检编号']}，口径 {run['口径版本']}，"
            f"分组 {run['对照组人数']}:{run['实验组人数']}，{run['开单结果']}）"
        )
        return {"ok": True, "message": message, "run": run, "work_order": work_order}

    def board_trigger_recheck(self, exp_code: str, metric_code: str, window: str,
                              result: str, p_value: float | None = None) -> dict[str, Any]:
        """数据证据看板上选中运行实验触发一次实际重新检验。

        新办一定使用当前确认版样本：直接开具并领取一张新办理单，再执行重检。
        若该实验存在缺证的在途办理单，缺证项只在证据看板展示缺项，不在此补发。
        """
        submitted = self.submit_ticket(exp_code, metric_code, window, remark="看板触发复查")
        if not submitted.get("ok"):
            return submitted
        ticket = submitted["ticket"]
        claimed = self.claim_ticket(int(ticket["id"]))
        if not claimed.get("ok"):
            return claimed
        return self.execute_recheck(int(ticket["id"]), result, p_value)

    # ------------------------------------------------------------------ #
    # 样本量核对工单
    # ------------------------------------------------------------------ #

    def list_work_orders(self, exp_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows("patrol_work_order")
        if exp_code:
            rows = [r for r in rows if r.get("实验编码") == exp_code]
        return rows

    def verify_work_order(self, work_order_id: int, note: str = "") -> dict[str, Any]:
        """完成样本量核对：核对结论回填后，待确认办理单才允许办结。"""
        work_order = store.find("patrol_work_order", work_order_id)
        if work_order is None:
            return {"ok": False, "message": "样本量核对工单不存在"}
        if work_order.get("status") != "待核对":
            return {"ok": False, "message": "工单已核对，不能重复办理"}
        work_order["status"] = "已核对"
        work_order["pending"] = False
        work_order["abnormal"] = False
        work_order["核对时间"] = _now()
        work_order["核对说明"] = note or "样本量核对完成，分组比例已确认"
        for ticket in store.rows(self.MODULE):
            if ticket.get("工单状态") == "待确认" and work_order.get("样本版本") in {
                ticket.get("样本版本"),
                next((r.get("样本版本") for r in store.rows("patrol_aa_run")
                      if r.get("id") == ticket.get("初次重算记录ID")), None),
            }:
                ticket["工单依据"] = self._ticket_basis(ticket)
        return {"ok": True, "message": f"工单 {work_order['工单编号']} 已核对", "work_order": work_order}

    # ------------------------------------------------------------------ #
    # 证据看板与办理单办结
    # ------------------------------------------------------------------ #

    def _work_order_for_version(self, sample_version: str | None) -> dict[str, Any] | None:
        if not sample_version:
            return None
        return next(
            (w for w in store.rows("patrol_work_order") if w.get("样本版本") == sample_version),
            None,
        )

    def _aa_line(self, exp_code: str, metric_code: str, window: str,
                 snapshot: dict[str, Any] | None) -> dict[str, Any]:
        """AA 预检证据行：区分已到证据、待确认与缺项；过期版不计入当前状态。"""
        if snapshot is None:
            return {
                "证据类型": "AA预检",
                "样本版本": None,
                "分配轮次": None,
                "状态": "缺项",
                "当前计入": False,
                "说明": "无已确认样本版本，AA 预检无法开展",
                "缺项": ["已确认样本快照", "AA重检结论"],
            }
        run = next(
            (r for r in store.rows("patrol_aa_run")
             if r.get("实验编码") == exp_code
             and r.get("指标编码") == metric_code
             and r.get("检验窗口") == window
             and r.get("样本版本") == snapshot.get("样本版本")
             and r.get("重检类型") == "实际重检"),
            None,
        )
        is_current = snapshot.get("status") == "已确认"
        if run is None:
            return {
                "证据类型": "AA预检",
                "样本版本": snapshot.get("样本版本"),
                "分配轮次": snapshot.get("分配轮次"),
                "状态": "待确认" if is_current else "已过期",
                "当前计入": is_current,
                "说明": (
                    "AA 预检器尚未领取或未完成实际重检" if is_current
                    else "该版本已过期且无实际重检，预检不计入当前状态，仅保留缺项记录"
                ),
                "缺项": ["AA实际重检结论"],
            }
        return {
            "证据类型": "AA预检",
            "样本版本": snapshot.get("样本版本"),
            "分配轮次": snapshot.get("分配轮次"),
            "状态": run.get("检验结论"),
            "当前计入": is_current,
            "重检编号": run.get("重检编号"),
            "口径版本": run.get("口径版本"),
            "分组": f"{run.get('对照组人数')}:{run.get('实验组人数')}",
            "检验时间": run.get("检验时间"),
            "说明": "当前确认版证据" if is_current else "历史版本证据，仅作已办结依据，不计入当前状态",
            "缺项": [],
        }

    def _ratio_line(self, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        """样本量核对证据行：未走完核对只呈现待确认与实际缺项，不显示零风险。"""
        if snapshot is None:
            return {
                "证据类型": "样本量核对",
                "样本版本": None,
                "分配轮次": None,
                "状态": "缺项",
                "当前计入": False,
                "说明": "无样本证据，无法计算两组份额",
                "缺项": ["分组人数", "份额核对结论"],
            }
        is_current = snapshot.get("status") == "已确认"
        work_order = self._work_order_for_version(snapshot.get("样本版本"))
        base = {
            "证据类型": "样本量核对",
            "样本版本": snapshot.get("样本版本"),
            "分配轮次": snapshot.get("分配轮次"),
            "对照组份额": snapshot.get("对照组份额"),
            "实验组份额": snapshot.get("实验组份额"),
            "份额差": snapshot.get("份额差"),
            "当前计入": is_current,
        }
        if work_order is None:
            # 份额差未超阈值：无需工单，但仍需显式给出「无需核对」结论，不能留白成零风险。
            if float(snapshot.get("份额差", 0)) <= RATIO_WORK_ORDER_THRESHOLD:
                return {
                    **base,
                    "状态": "无需核对" if is_current else "已过期",
                    "说明": f"份额差 {snapshot.get('份额差')} 未超 10pp 阈值"
                    + ("" if is_current else "；版本已过期，不计入当前状态"),
                    "缺项": [],
                }
            return {
                **base,
                "状态": "待确认" if is_current else "已过期",
                "说明": "份额差超阈值但核对工单尚未开具",
                "缺项": ["样本量核对工单"],
            }
        if work_order.get("status") == "待核对":
            return {
                **base,
                "状态": "待确认",
                "工单编号": work_order.get("工单编号"),
                "当前计入": is_current,
                "说明": (
                    f"核对工单 {work_order.get('工单编号')} 已开具待核对，分组比例尚未确认"
                    if is_current
                    else "该版本已过期，待核对工单仅作历史依据，不计入当前状态"
                ),
                "缺项": ["样本量核对结论"],
            }
        return {
            **base,
            "状态": "已核对",
            "工单编号": work_order.get("工单编号"),
            "当前计入": is_current,
            "核对说明": work_order.get("核对说明"),
            "说明": "样本量已核对确认" if is_current else "历史版本核对证据，不计入当前状态",
            "缺项": [],
        }

    def evidence_board(self, exp_code: str) -> dict[str, Any]:
        """异常实验钻入页：按「指标口径 × 分配轮次/样本版本」分别列证据到/缺情况。"""
        exp = next((r for r in store.rows("exp_design") if r.get("实验编码") == exp_code), None)
        if exp is None:
            return {"ok": False, "message": f"实验 {exp_code} 不存在"}
        metric_codes = sorted({
            str(t.get("指标编码")) for t in store.rows(self.MODULE)
            if t.get("实验编码") == exp_code and t.get("指标编码")
        })
        assumed = exp.get("假设指标")
        if assumed and assumed not in metric_codes:
            metric_codes.insert(0, str(assumed))
        calibers = self._metric_calibers(metric_codes)
        snapshots = [r for r in store.rows("patrol_snapshot") if r.get("实验编码") == exp_code]
        windows = sorted({
            str(t.get("检验窗口")) for t in store.rows(self.MODULE)
            if t.get("实验编码") == exp_code and t.get("检验窗口")
        })
        window = windows[0] if windows else "W1"
        groups = []
        for metric_code in metric_codes:
            caliber = calibers.get(metric_code, {"口径版本": None, "指标名称": None})
            if not snapshots:
                groups.append({
                    "指标编码": metric_code,
                    "口径版本": caliber.get("口径版本"),
                    "分配轮次": None,
                    "样本版本": None,
                    "证据行": [
                        self._aa_line(exp_code, metric_code, window, None),
                        self._ratio_line(None),
                    ],
                })
                continue
            for snapshot in snapshots:
                groups.append({
                    "指标编码": metric_code,
                    "口径版本": caliber.get("口径版本"),
                    "分配轮次": snapshot.get("分配轮次"),
                    "样本版本": snapshot.get("样本版本"),
                    "快照状态": snapshot.get("status"),
                    "证据行": [
                        self._aa_line(exp_code, metric_code, window, snapshot),
                        self._ratio_line(snapshot),
                    ],
                })
        current_snapshot = self.current_snapshot(exp_code)
        return {
            "ok": True,
            "实验编码": exp_code,
            "实验名称": exp.get("实验名称"),
            "当前样本版本": current_snapshot.get("样本版本") if current_snapshot else None,
            "证据组": groups,
            "在途办理单": [
                self.ticket_summary(t) for t in store.rows(self.MODULE)
                if t.get("实验编码") == exp_code and t.get("工单状态") != "已办结"
            ],
        }

    def _ticket_pending_work_orders(self, ticket: dict[str, Any]) -> list[dict[str, Any]]:
        """办理单关联的全部待核对工单：含当前实际检验版与冲突时的旧版初次重算。"""
        versions = {ticket.get("样本版本")}
        initial_run = next(
            (r for r in store.rows("patrol_aa_run") if r.get("id") == ticket.get("初次重算记录ID")),
            None,
        )
        if initial_run is not None:
            versions.add(initial_run.get("样本版本"))
        return [
            w for w in store.rows("patrol_work_order")
            if w.get("样本版本") in versions and w.get("status") == "待核对"
        ]

    def _ticket_basis(self, ticket: dict[str, Any]) -> dict[str, Any]:
        """重定位办理单实际检验/待处理状态所依据的证据快照。"""
        snapshot = next(
            (r for r in store.rows("patrol_snapshot")
             if r.get("样本版本") == ticket.get("样本版本")),
            None,
        )
        run = next(
            (r for r in store.rows("patrol_aa_run") if r.get("id") == ticket.get("重检记录ID")),
            None,
        )
        initial_run = next(
            (r for r in store.rows("patrol_aa_run") if r.get("id") == ticket.get("初次重算记录ID")),
            None,
        )
        work_order = self._work_order_for_version(ticket.get("样本版本"))
        return {
            "样本版本": ticket.get("样本版本"),
            "分配轮次": ticket.get("分配轮次"),
            "口径版本": ticket.get("口径版本"),
            "分组": (
                f"{snapshot.get('对照组人数')}:{snapshot.get('实验组人数')}"
                if snapshot else None
            ),
            "AA重检": (
                {"重检编号": run.get("重检编号"), "结论": run.get("检验结论"),
                 "分组": f"{run.get('对照组人数')}:{run.get('实验组人数')}",
                 "开单结果": run.get("开单结果"), "检验时间": run.get("检验时间")}
                if run else None
            ),
            "样本量工单": (
                {
                    "工单编号": work_order.get("工单编号"),
                    "状态": work_order.get("status"),
                    "份额差": work_order.get("份额差"),
                }
                if work_order else None
            ),
            "初次风险重算": (
                {
                    "重检编号": initial_run.get("重检编号"),
                    "样本版本": initial_run.get("样本版本"),
                    "分组": f"{initial_run.get('对照组人数')}:{initial_run.get('实验组人数')}",
                    "开单结果": initial_run.get("开单结果"),
                }
                if initial_run else None
            ),
        }

    def ticket_detail(self, ticket_id: int) -> dict[str, Any] | None:
        """打开巡检单：重新定位实际检验或待处理状态，并区分冻结依据与当前证据。"""
        ticket = store.find(self.MODULE, ticket_id)
        if ticket is None:
            return None
        detail = dict(ticket)
        detail["当前依据"] = self._ticket_basis(ticket)
        if ticket.get("工单状态") == "已办结":
            # 已办结：证据后来补齐也不改变办结时冻结的依据。
            detail["只读"] = True
            detail["当前状态提示"] = "办理单已办结，以下为办结时冻结的证据版次，后续重检不改写本单"
        else:
            detail["只读"] = False
            pending_work_orders = self._ticket_pending_work_orders(ticket)
            if pending_work_orders:
                detail["当前状态提示"] = (
                    "样本量核对工单待核对（"
                    + "、".join(w["工单编号"] for w in pending_work_orders)
                    + "），暂不能办结"
                )
            elif ticket.get("工单状态") == "待领取":
                detail["当前状态提示"] = "待 AA 预检器领取重检"
            else:
                detail["当前状态提示"] = "证据齐备，可办结"
        return detail

    def close_ticket(self, ticket_id: int) -> dict[str, Any]:
        """办结办理单并冻结当时证据版次；冻结后任何重检/补证都不改写本单依据。"""
        ticket = store.find(self.MODULE, ticket_id)
        if ticket is None:
            return {"ok": False, "message": "巡检办理单不存在"}
        if ticket.get("工单状态") == "已办结":
            return {"ok": False, "message": "办理单已办结，依据已冻结，不能重复办结"}
        if ticket.get("工单状态") == "待领取":
            return {"ok": False, "message": "办理单尚未领取重检，不能办结"}
        pending_work_orders = self._ticket_pending_work_orders(ticket)
        if pending_work_orders:
            return {
                "ok": False,
                "message": (
                    "样本量核对工单（"
                    + "、".join(w["工单编号"] for w in pending_work_orders)
                    + "）尚未核对，证据待确认不能办结"
                ),
            }
        ticket["工单状态"] = "已办结"
        ticket["status"] = "已办结"
        ticket["pending"] = False
        ticket["abnormal"] = False
        ticket["办结时间"] = _now()
        ticket["冻结证据"] = self._ticket_basis(ticket)
        ticket["工单依据"] = ticket["冻结证据"]
        return {"ok": True, "message": f"办理单 {ticket['工单编号']} 已办结并冻结证据版次", "ticket": ticket}

    def ticket_summary(self, ticket: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": ticket.get("id"),
            "工单编号": ticket.get("工单编号"),
            "实验编码": ticket.get("实验编码"),
            "指标编码": ticket.get("指标编码"),
            "口径版本": ticket.get("口径版本"),
            "检验窗口": ticket.get("检验窗口"),
            "分配轮次": ticket.get("分配轮次"),
            "样本版本": ticket.get("样本版本"),
            "登记样本版本": ticket.get("登记样本版本"),
            "工单状态": ticket.get("工单状态"),
            "版本冲突": ticket.get("版本冲突"),
            "初次核对工单编号": ticket.get("初次核对工单编号"),
        }

    # ------------------------------------------------------------------ #
    # 运营复盘材料（证据版次冻结 + 可重读）
    # ------------------------------------------------------------------ #

    def submit_retro(self, ticket_id: int, summary: str) -> dict[str, Any]:
        """提交复盘材料：冻结办理单同轮已确认的检验与样本数据版次。"""
        ticket = store.find(self.MODULE, ticket_id)
        if ticket is None:
            return {"ok": False, "message": "巡检办理单不存在"}
        if not str(summary or "").strip():
            return {"ok": False, "message": "复盘结论不能为空"}
        if ticket.get("工单状态") != "已办结":
            return {"ok": False, "message": "仅已办结办理单可提交复盘材料"}
        frozen = ticket.get("冻结证据") or self._ticket_basis(ticket)
        rows = store.rows("patrol_retro")
        retro = {
            "id": _next_id(rows),
            "status": "已提交",
            "pending": True,
            "abnormal": False,
            "材料编号": f"RT-{ticket['工单编号']}",
            "来源办理单": ticket.get("工单编号"),
            "实验编码": ticket.get("实验编码"),
            "指标编码": ticket.get("指标编码"),
            "复盘结论": summary,
            "提交时间": _now(),
            "冻结证据版次": frozen.get("样本版本"),
            "冻结证据": frozen,
            "确认时间": None,
        }
        rows.append(retro)
        return {"ok": True, "message": f"复盘材料 {retro['材料编号']} 已提交并冻结 {frozen.get('样本版本')} 证据", "retro": retro}

    def list_retros(self, exp_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows("patrol_retro")
        if exp_code:
            rows = [r for r in rows if r.get("实验编码") == exp_code]
        return rows

    def read_retro(self, retro_id: int) -> dict[str, Any] | None:
        """重读复盘材料保存时的证据版次；返回当前证据供对照，但不覆盖冻结版。"""
        retro = store.find("patrol_retro", retro_id)
        if retro is None:
            return None
        ticket = next(
            (t for t in store.rows(self.MODULE) if t.get("工单编号") == retro.get("来源办理单")),
            None,
        )
        current = self._ticket_basis(ticket) if ticket else None
        return {
            **retro,
            "当前证据版次": current,
            "版次是否变化": bool(current and current.get("样本版本") != retro.get("冻结证据版次")),
        }

    def confirm_retro(self, retro_id: int) -> dict[str, Any]:
        """确认复盘材料：确认后再发生的重检不会改写已确认材料。"""
        retro = store.find("patrol_retro", retro_id)
        if retro is None:
            return {"ok": False, "message": "复盘材料不存在"}
        if retro.get("status") == "已确认":
            return {"ok": False, "message": "材料已确认，内容与冻结证据均不可改写"}
        retro["status"] = "已确认"
        retro["pending"] = False
        retro["确认时间"] = _now()
        return {"ok": True, "message": f"复盘材料 {retro['材料编号']} 已确认，后续重检不改写本材料", "retro": retro}

    # ------------------------------------------------------------------ #
    # 运营复盘消费同轮确认数据
    # ------------------------------------------------------------------ #

    def consume_confirmed_round(self, exp_code: str, alloc_round: str) -> dict[str, Any]:
        """运营复盘消费同一分配轮次内已确认的检验与样本数据。

        轮次证据按该轮次当时确认的快照提供；即使后续已有更新版本，同轮已确认并
        固化在巡检单/复盘里的检验与样本仍可被复盘重读，不被新版覆盖。
        """
        snapshot = next(
            (r for r in store.rows("patrol_snapshot")
             if r.get("实验编码") == exp_code and r.get("分配轮次") == alloc_round),
            None,
        )
        runs = [
            r for r in store.rows("patrol_aa_run")
            if r.get("实验编码") == exp_code and r.get("分配轮次") == alloc_round
        ]
        work_orders = [
            w for w in store.rows("patrol_work_order")
            if w.get("实验编码") == exp_code and w.get("分配轮次") == alloc_round
        ]
        return {
            "ok": snapshot is not None,
            "实验编码": exp_code,
            "分配轮次": alloc_round,
            "样本证据": snapshot,
            "样本是否当前版": bool(snapshot and snapshot.get("status") == "已确认"),
            "已确认检验": [
                {
                    "重检编号": r.get("重检编号"),
                    "指标编码": r.get("指标编码"),
                    "口径版本": r.get("口径版本"),
                    "结论": r.get("检验结论"),
                    "样本版本": r.get("样本版本"),
                }
                for r in runs
            ],
            "样本量核对": [
                {
                    "工单编号": w.get("工单编号"),
                    "状态": w.get("status"),
                    "份额差": w.get("份额差"),
                }
                for w in work_orders
            ],
        }
