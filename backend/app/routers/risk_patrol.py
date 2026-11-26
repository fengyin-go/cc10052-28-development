"""风险巡检工作台路由：办理单、证据看板、AA 领取重检、核对工单与复盘材料。

路由层只做参数解析与结果包装，全部业务判断在 RiskPatrolService 内完成。
路径前缀 /api/risk-patrol 与通用资源路由 /api/risk_patrol 互不冲突。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import service_for
from app.services.risk_patrol import RiskPatrolService

router = APIRouter(prefix="/api/risk-patrol", tags=["风险巡检工作台"])


def patrol_service() -> RiskPatrolService:
    service = service_for("risk_patrol")
    assert isinstance(service, RiskPatrolService)
    return service


def unwrap(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "业务校验未通过"))
    return result


class SnapshotPayload(BaseModel):
    exp_code: str
    alloc_round: str
    ctrl_count: int = Field(ge=0)
    treat_count: int = Field(ge=0)


class TicketPayload(BaseModel):
    exp_code: str
    metric_code: str
    window: str
    remark: str | None = None


class RecheckPayload(BaseModel):
    result: str
    p_value: float | None = None


class BoardRecheckPayload(BaseModel):
    exp_code: str
    metric_code: str
    window: str
    result: str
    p_value: float | None = None


class WorkOrderPayload(BaseModel):
    note: str | None = None


class RetroPayload(BaseModel):
    ticket_id: int
    summary: str


@router.get("/experiments")
def running_experiments() -> dict[str, Any]:
    """工作台入口：可选中的运行中实验及其当前口径、样本证据对照。"""
    return {"ok": True, "items": patrol_service().running_experiments()}


@router.get("/snapshots")
def list_snapshots(exp_code: str | None = None) -> dict[str, Any]:
    return {"ok": True, "items": patrol_service().list_snapshots(exp_code)}


@router.post("/snapshots/confirm")
def confirm_snapshot(payload: SnapshotPayload) -> dict[str, Any]:
    """分组更正后确认新样本版本，旧确认版自动转过期。"""
    return unwrap(patrol_service().confirm_snapshot(
        payload.exp_code, payload.alloc_round, payload.ctrl_count, payload.treat_count,
    ))


@router.post("/tickets")
def submit_ticket(payload: TicketPayload) -> dict[str, Any]:
    """运营负责人提交运行指标及窗口复查，服务端开具巡检办理单。"""
    return unwrap(patrol_service().submit_ticket(
        payload.exp_code, payload.metric_code, payload.window, payload.remark or "",
    ))


@router.get("/tickets")
def list_tickets(exp_code: str | None = None, status: str | None = None) -> dict[str, Any]:
    service = patrol_service()
    items = service.list_entries(filters={"实验编码": exp_code} if exp_code else None,
                                 status=status, page=1, size=200)[0]
    return {"ok": True, "items": [service.ticket_summary(t) for t in items]}


@router.get("/tickets/claimable")
def list_claimable() -> dict[str, Any]:
    """AA 预检器领取队列：实际要检的实验轮次。"""
    service = patrol_service()
    return {"ok": True, "items": [service.ticket_summary(t) for t in service.list_claimable()]}


@router.get("/tickets/{ticket_id}")
def ticket_detail(ticket_id: int) -> dict[str, Any]:
    detail = patrol_service().ticket_detail(ticket_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="巡检办理单不存在")
    return {"ok": True, "item": detail}


@router.post("/tickets/{ticket_id}/claim")
def claim_ticket(ticket_id: int) -> dict[str, Any]:
    """AA 预检器领取办理单，解析实际检验轮次与样本版本，登记版本冲突。"""
    return unwrap(patrol_service().claim_ticket(ticket_id))


@router.post("/tickets/{ticket_id}/recheck")
def execute_recheck(ticket_id: int, payload: RecheckPayload) -> dict[str, Any]:
    """执行一次实际 AA 重检，记录适用口径与分组，必要时开具样本量核对工单。"""
    return unwrap(patrol_service().execute_recheck(ticket_id, payload.result, payload.p_value))


@router.post("/recheck/board-trigger")
def board_trigger_recheck(payload: BoardRecheckPayload) -> dict[str, Any]:
    """数据证据看板选中实验触发一次实际重新检验，新办一定使用当前确认版。"""
    return unwrap(patrol_service().board_trigger_recheck(
        payload.exp_code, payload.metric_code, payload.window, payload.result, payload.p_value,
    ))


@router.get("/runs")
def list_runs(exp_code: str | None = None) -> dict[str, Any]:
    return {"ok": True, "items": patrol_service().list_runs(exp_code)}


@router.get("/work-orders")
def list_work_orders(exp_code: str | None = None) -> dict[str, Any]:
    return {"ok": True, "items": patrol_service().list_work_orders(exp_code)}


@router.post("/work-orders/{work_order_id}/verify")
def verify_work_order(work_order_id: int, payload: WorkOrderPayload) -> dict[str, Any]:
    """完成样本量核对，回填核对结论。"""
    return unwrap(patrol_service().verify_work_order(work_order_id, payload.note or ""))


@router.post("/tickets/{ticket_id}/close")
def close_ticket(ticket_id: int) -> dict[str, Any]:
    """办结办理单并冻结当时证据版次。"""
    return unwrap(patrol_service().close_ticket(ticket_id))


@router.get("/evidence/{exp_code}")
def evidence_board(exp_code: str) -> dict[str, Any]:
    """从看板钻入异常实验：展示哪些证据已到、哪些仍需办理。"""
    return unwrap(patrol_service().evidence_board(exp_code))


@router.post("/retros")
def submit_retro(payload: RetroPayload) -> dict[str, Any]:
    """提交复盘材料并冻结同轮检验与样本证据版次。"""
    return unwrap(patrol_service().submit_retro(payload.ticket_id, payload.summary))


@router.get("/retros")
def list_retros(exp_code: str | None = None) -> dict[str, Any]:
    return {"ok": True, "items": patrol_service().list_retros(exp_code)}


@router.get("/retros/{retro_id}")
def read_retro(retro_id: int) -> dict[str, Any]:
    """重读复盘材料保存时的证据版次，并对照当前版次。"""
    retro = patrol_service().read_retro(retro_id)
    if retro is None:
        raise HTTPException(status_code=404, detail="复盘材料不存在")
    return {"ok": True, "item": retro}


@router.post("/retros/{retro_id}/confirm")
def confirm_retro(retro_id: int) -> dict[str, Any]:
    """确认复盘材料；确认后重检不改写材料。"""
    return unwrap(patrol_service().confirm_retro(retro_id))


@router.get("/rounds/{exp_code}/{alloc_round}/confirmed")
def consume_confirmed_round(exp_code: str, alloc_round: str) -> dict[str, Any]:
    """运营复盘消费同轮确认的检验与样本数据。"""
    return patrol_service().consume_confirmed_round(exp_code, alloc_round)
