/**
 * 风险巡检工作台接口封装。
 * 后端领域：巡检办理单 / 样本证据快照 / AA 实际重检 / 样本量核对工单 / 运营复盘。
 */
import { request } from './client'

const BASE = '/api/risk-patrol'

export type EvidenceLine = {
  证据类型: string
  样本版本: string | null
  分配轮次: string | null
  状态: string
  当前计入: boolean
  说明: string
  缺项: string[]
  分组?: string
  口径版本?: string
  重检编号?: string
  工单编号?: string
  对照组份额?: number
  实验组份额?: number
  份额差?: number
  核对说明?: string
  检验时间?: string
}

export type EvidenceGroup = {
  指标编码: string
  口径版本: string | null
  分配轮次: string | null
  样本版本: string | null
  快照状态?: string
  证据行: EvidenceLine[]
}

export type PatrolTicket = {
  id: number
  工单编号: string
  实验编码: string
  指标编码: string
  口径版本: string
  检验窗口: string
  分配轮次: string | null
  样本版本: string | null
  登记样本版本: string | null
  工单状态: string
  版本冲突: boolean
  冲突说明?: string
  初次核对工单编号?: string | null
  只读?: boolean
  当前状态提示?: string
  冻结证据?: Record<string, unknown> | null
  当前依据?: Record<string, unknown>
}

async function asJson<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T & { detail?: string }
  if (!response.ok) {
    throw new Error(payload.detail ?? `接口返回 ${response.status}`)
  }
  return payload
}

function get<T>(path: string): Promise<T> {
  return request(`${BASE}${path}`).then(asJson<T>)
}

function post<T>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  return request(`${BASE}${path}`, { method: 'POST', body: JSON.stringify(body) }).then(asJson<T>)
}

export function listExperiments() {
  return get<{ ok: boolean; items: Record<string, unknown>[] }>('/experiments')
}

export function listSnapshots(expCode?: string) {
  return get<{ ok: boolean; items: Record<string, unknown>[] }>(
    expCode ? `/snapshots?exp_code=${encodeURIComponent(expCode)}` : '/snapshots',
  )
}

export function confirmSnapshot(body: {
  exp_code: string
  alloc_round: string
  ctrl_count: number
  treat_count: number
}) {
  return post<{ ok: boolean; message: string }>('/snapshots/confirm', body)
}

export function submitTicket(body: {
  exp_code: string
  metric_code: string
  window: string
  remark?: string
}) {
  return post<{ ok: boolean; message: string; ticket: PatrolTicket }>('/tickets', body)
}

export function listTickets(status?: string) {
  return get<{ ok: boolean; items: PatrolTicket[] }>(
    status ? `/tickets?status=${encodeURIComponent(status)}` : '/tickets',
  )
}

export function listClaimable() {
  return get<{ ok: boolean; items: PatrolTicket[] }>('/tickets/claimable')
}

export function ticketDetail(id: number) {
  return get<{ ok: boolean; item: PatrolTicket }>(`/tickets/${id}`)
}

export function claimTicket(id: number) {
  return post<{
    ok: boolean
    message: string
    版本冲突: boolean
    ticket: PatrolTicket
  }>(`/tickets/${id}/claim`)
}

export function executeRecheck(id: number, body: { result: string; p_value?: number | null }) {
  return post<{ ok: boolean; message: string }>(`/tickets/${id}/recheck`, body)
}

export function boardTriggerRecheck(body: {
  exp_code: string
  metric_code: string
  window: string
  result: string
  p_value?: number | null
}) {
  return post<{ ok: boolean; message: string }>('/recheck/board-trigger', body)
}

export function listRuns(expCode?: string) {
  return get<{ ok: boolean; items: Record<string, unknown>[] }>(
    expCode ? `/runs?exp_code=${encodeURIComponent(expCode)}` : '/runs',
  )
}

export function listWorkOrders(expCode?: string) {
  return get<{ ok: boolean; items: Record<string, unknown>[] }>(
    expCode ? `/work-orders?exp_code=${encodeURIComponent(expCode)}` : '/work-orders',
  )
}

export function verifyWorkOrder(id: number, note?: string) {
  return post<{ ok: boolean; message: string }>(`/work-orders/${id}/verify`, { note })
}

export function closeTicket(id: number) {
  return post<{ ok: boolean; message: string }>(`/tickets/${id}/close`)
}

export function evidenceBoard(expCode: string) {
  return get<{
    ok: boolean
    实验编码: string
    实验名称: string
    当前样本版本: string | null
    证据组: EvidenceGroup[]
    在途办理单: PatrolTicket[]
  }>(`/evidence/${encodeURIComponent(expCode)}`)
}

export function submitRetro(body: { ticket_id: number; summary: string }) {
  return post<{ ok: boolean; message: string }>('/retros', body)
}

export function listRetros(expCode?: string) {
  return get<{ ok: boolean; items: Record<string, unknown>[] }>(
    expCode ? `/retros?exp_code=${encodeURIComponent(expCode)}` : '/retros',
  )
}

export function readRetro(id: number) {
  return get<{ ok: boolean; item: Record<string, unknown> }>(`/retros/${id}`)
}

export function confirmRetro(id: number) {
  return post<{ ok: boolean; message: string }>(`/retros/${id}/confirm`)
}

export function consumeConfirmedRound(expCode: string, allocRound: string) {
  return get<{ ok: boolean; items?: never } | Record<string, unknown>>(
    `/rounds/${encodeURIComponent(expCode)}/${encodeURIComponent(allocRound)}/confirmed`,
  )
}
