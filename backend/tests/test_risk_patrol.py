#!/usr/bin/env python3
"""风险巡检工作台领域回归测试：直接驱动 RiskPatrolService，仅依赖标准库。

运行：cd backend && .venv/bin/python -m tests.test_risk_patrol
覆盖：办理单开具/领取/版本冲突、AA 实际重检、样本量核对工单阈值与去重、
证据看板缺项与过期不计当前、办结冻结、复盘证据版次冻结与同轮消费。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import service_for  # noqa: E402
from app.services.risk_patrol import RiskPatrolService  # noqa: E402
from app.store import store  # noqa: E402


class RiskPatrolWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例重建内存仓库，恢复种子数据（E1-V1 为 6:4），并取回全新服务。
        store.__init__()
        self.service: RiskPatrolService = service_for("risk_patrol")  # type: ignore[assignment]

    def _ticket_id(self, result: dict) -> int:
        return int(result["ticket"]["id"])

    def test_full_workflow_with_version_conflict(self) -> None:
        svc = self.service

        # 1. 提交复查：范围只到指标与窗口，未锁样本版。
        ticket = svc.submit_ticket("E1", "M1", "W1")["ticket"]
        self.assertIsNone(ticket["样本版本"])
        self.assertEqual(ticket["登记样本版本"], "E1-V1")

        # 2. AA 领取前分组更正确认 V2（5:5），V1 转过期，在途单标记冲突。
        snap = svc.confirm_snapshot("E1", "R2", 50, 50)
        self.assertEqual(snap["snapshot"]["样本版本"], "E1-V2")
        self.assertEqual(snap["冲突办理单数"], 1)
        self.assertEqual(svc.current_snapshot("E1")["样本版本"], "E1-V2")

        # 3. 领取：冲突 + 旧版 V1 初次风险重算（6:4，差 20pp 开旧版工单）。
        claim = svc.claim_ticket(int(ticket["id"]))
        self.assertTrue(claim["版本冲突"])
        self.assertEqual(claim["ticket"]["样本版本"], "E1-V2")
        initial = claim["初次风险重算"]
        self.assertEqual(initial["样本版本"], "E1-V1")
        self.assertEqual((initial["对照组人数"], initial["实验组人数"]), (60, 40))
        self.assertEqual(initial["核对工单编号"], "WO-E1-V1")
        self.assertIsNone(claim["ticket"]["重检记录ID"])

        # 4. 一次实际重检按 V2（5:5）执行，不再开单；重复重检被拒。
        recheck = svc.execute_recheck(int(ticket["id"]), "无显著差异", 0.62)
        self.assertIsNone(recheck["work_order"])
        self.assertEqual(recheck["run"]["对照组人数"], 50)
        self.assertEqual(recheck["run"]["口径版本"], "CAL-V1")
        dup = svc.execute_recheck(int(ticket["id"]), "检出差异")
        self.assertFalse(dup["ok"])

        # 5. 看板再发起一笔复查，新办一定用当前 V2 且不开单。
        board = svc.board_trigger_recheck("E1", "M1", "W1", "无显著差异")
        self.assertEqual(board["run"]["样本版本"], "E1-V2")
        self.assertIsNone(board["work_order"])

        # 6. 证据看板：过期 V1 缺项不计当前；待确认行不显示零风险；不同轮次分列。
        board_ev = svc.evidence_board("E1")
        versions = {g["样本版本"] for g in board_ev["证据组"]}
        self.assertIn("E1-V1", versions)
        self.assertIn("E1-V2", versions)
        g_v1 = next(g for g in board_ev["证据组"] if g["样本版本"] == "E1-V1")
        ratio_v1 = next(x for x in g_v1["证据行"] if x["证据类型"] == "样本量核对")
        aa_v1 = next(x for x in g_v1["证据行"] if x["证据类型"] == "AA预检")
        self.assertEqual(ratio_v1["状态"], "待确认")
        self.assertEqual(ratio_v1["缺项"], ["样本量核对结论"])
        self.assertFalse(ratio_v1["当前计入"])
        self.assertFalse(aa_v1["当前计入"])
        self.assertIn("AA实际重检结论", aa_v1["缺项"])

        # 7. 工单未核对不能办结；核对后可办结并冻结 V2。
        self.assertFalse(svc.close_ticket(int(ticket["id"]))["ok"])
        wo = next(w for w in svc.list_work_orders("E1") if w["工单编号"] == "WO-E1-V1")
        svc.verify_work_order(int(wo["id"]), "已人工核对")
        closed = svc.close_ticket(int(ticket["id"]))
        self.assertTrue(closed["ok"])
        self.assertEqual(closed["ticket"]["冻结证据"]["样本版本"], "E1-V2")
        self.assertEqual(
            closed["ticket"]["冻结证据"]["初次风险重算"]["样本版本"], "E1-V1",
        )

        # 8. 再确认 V3，已办结依据与只读状态不变。
        svc.confirm_snapshot("E1", "R3", 55, 45)
        detail = svc.ticket_detail(int(ticket["id"]))
        self.assertTrue(detail["只读"])
        self.assertEqual(detail["冻结证据"]["样本版本"], "E1-V2")

        # 9. 复盘材料冻结 V2，可重读，确认后不可改写。
        retro = svc.submit_retro(int(ticket["id"]), "首轮复盘")
        retro_id = int(retro["retro"]["id"])
        self.assertEqual(retro["retro"]["冻结证据版次"], "E1-V2")
        self.assertEqual(svc.read_retro(retro_id)["冻结证据版次"], "E1-V2")
        self.assertTrue(svc.confirm_retro(retro_id)["ok"])
        self.assertFalse(svc.confirm_retro(retro_id)["ok"])

        # 10. 同轮确认数据可被运营复盘消费，旧轮次证据仍可重读但非当前版。
        round2 = svc.consume_confirmed_round("E1", "R2")
        self.assertTrue(round2["ok"])
        self.assertEqual(round2["样本证据"]["样本版本"], "E1-V2")
        self.assertEqual(len(round2["已确认检验"]), 2)
        self.assertEqual(round2["样本量核对"], [])
        round1 = svc.consume_confirmed_round("E1", "R1")
        self.assertTrue(round1["ok"])
        self.assertFalse(round1["样本是否当前版"])
        self.assertEqual(round1["样本量核对"][0]["工单编号"], "WO-E1-V1")

    def test_threshold_boundary_dedup_and_missing_evidence(self) -> None:
        svc = self.service

        # 缺证实验：证据行为缺项（无结果、非零风险），领取被拒。
        ev2 = svc.evidence_board("E2")
        self.assertTrue(all(line["状态"] == "缺项" for line in ev2["证据组"][0]["证据行"]))
        t_e2 = svc.submit_ticket("E2", "M2", "W1")
        self.assertFalse(svc.claim_ticket(self._ticket_id(t_e2))["ok"])

        # 份额差恰好 10pp（55:45）：不超阈值，不开工单。
        svc.confirm_snapshot("E1", "R4", 55, 45)
        boundary = svc.board_trigger_recheck("E1", "M1", "W1", "无显著差异")
        self.assertIsNone(boundary["work_order"])

        # 份额差 30pp（65:35）：同版本两张办理单只复用一张待核对工单。
        svc.confirm_snapshot("E1", "R5", 65, 35)
        ta = svc.submit_ticket("E1", "M1", "W1")
        tb = svc.submit_ticket("E1", "M1", "W2")
        svc.claim_ticket(self._ticket_id(ta))
        svc.claim_ticket(self._ticket_id(tb))
        svc.execute_recheck(self._ticket_id(ta), "无显著差异")
        svc.execute_recheck(self._ticket_id(tb), "检出差异")
        r5_orders = [w for w in svc.list_work_orders("E1") if w["分配轮次"] == "R5"]
        self.assertEqual(len(r5_orders), 1)
        self.assertEqual(r5_orders[0]["份额差"], 0.3)
        self.assertEqual(r5_orders[0]["status"], "待核对")

    def test_calibers_and_rounds_listed_separately(self) -> None:
        svc = self.service
        svc.submit_ticket("E1", "M1", "W1")
        svc.submit_ticket("E1", "M2", "W1")
        svc.confirm_snapshot("E1", "R2", 50, 50)
        groups = svc.evidence_board("E1")["证据组"]
        keys = {(g["指标编码"], g["样本版本"]) for g in groups}
        # 两个口径 × 两个版本（V1 已过期 + V2 当前）分别成组，互不合并。
        self.assertEqual(keys, {("M1", "E1-V1"), ("M1", "E1-V2"),
                                ("M2", "E1-V1"), ("M2", "E1-V2")})


if __name__ == "__main__":
    unittest.main(verbosity=2)
