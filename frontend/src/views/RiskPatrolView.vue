<template>
  <section class="page patrol-page" data-testid="risk-patrol">
    <header class="page-head">
      <div>
        <h2>风险巡检工作台</h2>
        <p class="page-desc">
          负责人选中运行实验发起风险巡检，服务端开具巡检办理单；AA 预检器领取实际轮次重检，
          证据按指标口径 × 分配轮次分列，办结与复盘冻结证据版次。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" data-testid="refresh" @click="reloadAll">刷新工作台</button>
      </div>
    </header>

    <nav class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
        <span v-if="tab.badge" class="tab-badge">{{ tab.badge }}</span>
      </button>
    </nav>

    <p v-if="errorMessage" class="error-text" data-testid="patrol-error">{{ errorMessage }}</p>
    <p v-if="infoMessage" class="info-text" data-testid="patrol-info">{{ infoMessage }}</p>

    <!-- ============ 1. 巡检工作台：运行实验 + 发起复查 ============ -->
    <div v-if="activeTab === 'workbench'">
      <h3 class="section-title">运行中实验（对照当前口径与样本证据）</h3>
      <table class="data-table" data-testid="experiment-table">
        <thead>
          <tr>
            <th>实验编码</th><th>实验名称</th><th>假设指标</th>
            <th>当前样本版本</th><th>当前分配轮次</th><th>待处理巡检</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="exp in experiments" :key="String(exp.实验编码)" :data-testid="`exp-${exp.实验编码}`">
            <td>{{ exp.实验编码 }}</td>
            <td>{{ exp.实验名称 }}</td>
            <td>{{ exp.假设指标 }}</td>
            <td>
              <span v-if="exp.当前样本版本">{{ exp.当前样本版本 }}</span>
              <span v-else class="tag tag-missing">缺样本证据</span>
            </td>
            <td>{{ exp.当前分配轮次 ?? '—' }}</td>
            <td>
              <span :class="['tag', exp.待处理巡检数 ? 'tag-pending' : 'tag-ok']">{{ exp.待处理巡检数 }}</span>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="openSubmit(String(exp.实验编码), String(exp.假设指标))">
                发起风险巡检
              </button>
              <button class="link" type="button" @click="openEvidence(String(exp.实验编码))">
                钻入证据看板
              </button>
            </td>
          </tr>
          <tr v-if="!experiments.length">
            <td colspan="7" class="empty-state">暂无运行中实验</td>
          </tr>
        </tbody>
      </table>

      <h3 class="section-title">样本证据版本（分组更正入口）</h3>
      <table class="data-table" data-testid="snapshot-table">
        <thead>
          <tr>
            <th>样本版本</th><th>实验</th><th>分配轮次</th><th>对照组:实验组</th>
            <th>对照份额</th><th>实验份额</th><th>份额差</th><th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="snap in snapshots" :key="String(snap.id)" :data-status="String(snap.status)">
            <td>{{ snap.样本版本 }}</td>
            <td>{{ snap.实验编码 }}</td>
            <td>{{ snap.分配轮次 }}</td>
            <td>{{ snap.对照组人数 }}:{{ snap.实验组人数 }}</td>
            <td>{{ formatShare(snap.对照组份额) }}</td>
            <td>{{ formatShare(snap.实验组份额) }}</td>
            <td>
              <span :class="['tag', Number(snap.份额差) > 0.1 ? 'tag-danger' : 'tag-ok']">
                {{ formatShare(snap.份额差) }}
              </span>
            </td>
            <td>
              <span :class="['tag', snap.status === '已确认' ? 'tag-ok' : 'tag-expired']">{{ snap.status }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ============ 2. AA 预检器领取队列 ============ -->
    <div v-if="activeTab === 'claim'">
      <h3 class="section-title">AA 预检器待领取办理单（领取实际要检的实验轮次）</h3>
      <table class="data-table" data-testid="claim-table">
        <thead>
          <tr>
            <th>工单编号</th><th>实验</th><th>指标/窗口</th><th>口径版本</th>
            <th>登记样本版本</th><th>版本冲突</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ticket in claimable" :key="ticket.id" :data-testid="`claim-${ticket.id}`">
            <td>{{ ticket.工单编号 }}</td>
            <td>{{ ticket.实验编码 }}</td>
            <td>{{ ticket.指标编码 }} / {{ ticket.检验窗口 }}</td>
            <td>{{ ticket.口径版本 }}</td>
            <td>{{ ticket.登记样本版本 ?? '—' }}</td>
            <td>
              <span v-if="ticket.版本冲突" class="tag tag-danger">冲突（领取按当前版）</span>
              <span v-else class="tag tag-ok">无冲突</span>
            </td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`claim-btn-${ticket.id}`" @click="onClaim(ticket.id)">
                领取并解析轮次
              </button>
            </td>
          </tr>
          <tr v-if="!claimable.length">
            <td colspan="7" class="empty-state">领取队列已清空，没有待检办理单</td>
          </tr>
        </tbody>
      </table>

      <h3 class="section-title">检验中 / 待确认办理单（执行一次实际重检）</h3>
      <table class="data-table" data-testid="recheck-table">
        <thead>
          <tr>
            <th>工单编号</th><th>实验</th><th>实际样本版本</th><th>轮次</th>
            <th>状态</th><th>关联核对工单</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ticket in activeTickets" :key="ticket.id" :data-testid="`active-${ticket.id}`">
            <td>{{ ticket.工单编号 }}</td>
            <td>{{ ticket.实验编码 }}</td>
            <td>{{ ticket.样本版本 ?? '—' }}</td>
            <td>{{ ticket.分配轮次 ?? '—' }}</td>
            <td><span class="tag tag-pending">{{ ticket.工单状态 }}</span></td>
            <td>{{ ticket.初次核对工单编号 ? `初次重算 ${ticket.初次核对工单编号}` : '—' }}</td>
            <td class="row-actions">
              <button
                v-if="ticket.工单状态 === '检验中'"
                class="link"
                type="button"
                :data-testid="`recheck-btn-${ticket.id}`"
                @click="onRecheck(ticket.id, '无显著差异')"
              >
                实际重检（无差异）
              </button>
              <button
                v-if="ticket.工单状态 === '检验中'"
                class="link"
                type="button"
                @click="onRecheck(ticket.id, '检出差异')"
              >
                实际重检（检出差异）
              </button>
              <button class="link" type="button" @click="openTicket(ticket.id)">打开巡检单</button>
            </td>
          </tr>
          <tr v-if="!activeTickets.length">
            <td colspan="7" class="empty-state">暂无检验中或待确认办理单</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ============ 3. 异常实验证据看板（钻入） ============ -->
    <div v-if="activeTab === 'evidence'">
      <div class="filter-bar">
        <label class="filter-item">
          <span>实验编码</span>
          <input v-model="evidenceExpCode" data-testid="evidence-exp-input" placeholder="如 E1" />
        </label>
        <button class="btn primary" type="button" data-testid="evidence-query" @click="loadEvidence">查看证据到/缺情况</button>
      </div>

      <template v-if="evidence">
        <h3 class="section-title">
          {{ evidence.实验名称 }}（{{ evidence.实验编码 }}）证据看板
          <span class="muted">当前样本版本：{{ evidence.当前样本版本 ?? '无' }}</span>
        </h3>
        <div
          v-for="group in evidence.证据组"
          :key="`${group.指标编码}-${group.样本版本 ?? 'none'}`"
          class="evidence-card"
          :data-testid="`evidence-group-${group.样本版本 ?? 'none'}`"
        >
          <div class="evidence-head">
            <strong>指标 {{ group.指标编码 }}</strong>
            <span class="muted">口径 {{ group.口径版本 ?? '—' }}</span>
            <span class="muted">轮次 {{ group.分配轮次 ?? '—' }}</span>
            <span class="muted">样本版本 {{ group.样本版本 ?? '—' }}</span>
            <span v-if="group.快照状态" :class="['tag', group.快照状态 === '已确认' ? 'tag-ok' : 'tag-expired']">
              {{ group.快照状态 }}
            </span>
          </div>
          <table class="data-table sub-table">
            <thead>
              <tr><th>证据类型</th><th>状态</th><th>是否计入当前</th><th>实际缺项</th><th>说明</th></tr>
            </thead>
            <tbody>
              <tr v-for="line in group.证据行" :key="line.证据类型" :data-testid="`evidence-line-${line.证据类型}`">
                <td>{{ line.证据类型 }}</td>
                <td>
                  <span :class="['tag', lineStatusClass(line)]">{{ line.状态 }}</span>
                  <span v-if="line.分组" class="muted">（分组 {{ line.分组 }}）</span>
                </td>
                <td>
                  <span :class="['tag', line.当前计入 ? 'tag-ok' : 'tag-expired']">
                    {{ line.当前计入 ? '计入当前' : '不计入当前' }}
                  </span>
                </td>
                <td>
                  <span v-if="line.缺项.length" class="tag tag-danger">{{ line.缺项.join('、') }}</span>
                  <span v-else class="tag tag-ok">无缺项</span>
                </td>
                <td class="muted">{{ line.说明 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <h3 class="section-title">在途办理单</h3>
        <table class="data-table">
          <thead><tr><th>工单编号</th><th>指标/窗口</th><th>样本版本</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="ticket in evidence.在途办理单" :key="ticket.id">
              <td>{{ ticket.工单编号 }}</td>
              <td>{{ ticket.指标编码 }} / {{ ticket.检验窗口 }}</td>
              <td>{{ ticket.样本版本 ?? ticket.登记样本版本 ?? '—' }}</td>
              <td><span class="tag tag-pending">{{ ticket.工单状态 }}</span></td>
              <td><button class="link" type="button" @click="openTicket(ticket.id)">打开巡检单</button></td>
            </tr>
            <tr v-if="!evidence.在途办理单.length">
              <td colspan="5" class="empty-state">该实验暂无在途办理单</td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>

    <!-- ============ 4. 办理单与工单 ============ -->
    <div v-if="activeTab === 'tickets'">
      <h3 class="section-title">全部巡检办理单</h3>
      <table class="data-table" data-testid="ticket-table">
        <thead>
          <tr>
            <th>工单编号</th><th>实验</th><th>指标/窗口</th><th>口径</th>
            <th>登记版→实际版</th><th>冲突</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ticket in tickets" :key="ticket.id" :data-testid="`ticket-${ticket.id}`">
            <td>{{ ticket.工单编号 }}</td>
            <td>{{ ticket.实验编码 }}</td>
            <td>{{ ticket.指标编码 }} / {{ ticket.检验窗口 }}</td>
            <td>{{ ticket.口径版本 }}</td>
            <td>{{ ticket.登记样本版本 ?? '—' }} → {{ ticket.样本版本 ?? '待领取解析' }}</td>
            <td>
              <span v-if="ticket.版本冲突" class="tag tag-danger">冲突</span>
              <span v-else class="tag tag-ok">—</span>
            </td>
            <td><span class="tag tag-pending">{{ ticket.工单状态 }}</span></td>
            <td class="row-actions">
              <button class="link" type="button" @click="openTicket(ticket.id)">打开巡检单</button>
            </td>
          </tr>
        </tbody>
      </table>

      <h3 class="section-title">样本量核对工单（份额差 &gt; 10pp 才开具）</h3>
      <table class="data-table" data-testid="work-order-table">
        <thead>
          <tr>
            <th>工单编号</th><th>实验</th><th>轮次</th><th>样本版本</th>
            <th>对照份额</th><th>实验份额</th><th>份额差</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="wo in workOrders" :key="String(wo.id)" :data-testid="`wo-${wo.id}`">
            <td>{{ wo.工单编号 }}</td>
            <td>{{ wo.实验编码 }}</td>
            <td>{{ wo.分配轮次 }}</td>
            <td>{{ wo.样本版本 }}</td>
            <td>{{ formatShare(wo.对照组份额) }}</td>
            <td>{{ formatShare(wo.实验组份额) }}</td>
            <td><span class="tag tag-danger">{{ formatShare(wo.份额差) }}</span></td>
            <td>
              <span :class="['tag', wo.status === '已核对' ? 'tag-ok' : 'tag-pending']">{{ wo.status }}</span>
            </td>
            <td>
              <button v-if="wo.status === '待核对'" class="link" type="button" @click="onVerifyWorkOrder(Number(wo.id))">
                完成核对
              </button>
              <span v-else class="muted">{{ wo.核对说明 }}</span>
            </td>
          </tr>
          <tr v-if="!workOrders.length">
            <td colspan="9" class="empty-state">暂无超阈值核对工单（5:5 等均衡分组不会开单，也不显示为零风险）</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ============ 5. 运营复盘 ============ -->
    <div v-if="activeTab === 'retro'">
      <h3 class="section-title">运营复盘材料（提交即冻结证据版次，可重读）</h3>
      <table class="data-table" data-testid="retro-table">
        <thead>
          <tr>
            <th>材料编号</th><th>来源办理单</th><th>实验</th><th>指标</th>
            <th>冻结证据版次</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="retro in retros" :key="String(retro.id)" :data-testid="`retro-${retro.id}`">
            <td>{{ retro.材料编号 }}</td>
            <td>{{ retro.来源办理单 }}</td>
            <td>{{ retro.实验编码 }}</td>
            <td>{{ retro.指标编码 }}</td>
            <td><span class="tag tag-ok">{{ retro.冻结证据版次 }}</span></td>
            <td><span class="tag tag-pending">{{ retro.status }}</span></td>
            <td class="row-actions">
              <button class="link" type="button" @click="onReadRetro(Number(retro.id))">重读证据版次</button>
              <button v-if="retro.status !== '已确认'" class="link" type="button" @click="onConfirmRetro(Number(retro.id))">
                确认材料
              </button>
            </td>
          </tr>
          <tr v-if="!retros.length">
            <td colspan="7" class="empty-state">暂无复盘材料（仅已办结办理单可提交）</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ============ 发起巡检弹窗 ============ -->
    <div v-if="showSubmit" class="modal-backdrop" data-testid="submit-modal">
      <form class="modal" @submit.prevent="onSubmitTicket">
        <h3>发起风险巡检</h3>
        <p class="muted small">获准范围只到指标与窗口，申请不锁定样本版，AA 领取时按当前确认版解析。</p>
        <label class="create-field">
          <span>实验编码</span>
          <input v-model="submitForm.exp_code" data-testid="submit-exp" required readonly />
        </label>
        <label class="create-field">
          <span>指标编码（口径）</span>
          <input v-model="submitForm.metric_code" data-testid="submit-metric" required />
        </label>
        <label class="create-field">
          <span>检验窗口</span>
          <input v-model="submitForm.window" data-testid="submit-window" placeholder="如 W1" required />
        </label>
        <label class="create-field">
          <span>备注</span>
          <input v-model="submitForm.remark" data-testid="submit-remark" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showSubmit = false">取消</button>
          <button class="btn primary" type="submit" data-testid="submit-confirm">开具巡检办理单</button>
        </div>
      </form>
    </div>

    <!-- ============ 巡检单详情弹窗（重定位实际检验/待处理 + 冻结依据） ============ -->
    <div v-if="ticketDetail" class="modal-backdrop" data-testid="ticket-modal">
      <div class="modal wide">
        <h3>巡检单 {{ ticketDetail.工单编号 }}</h3>
        <p :class="ticketDetail.只读 ? 'info-text' : 'muted'">{{ ticketDetail.当前状态提示 }}</p>
        <div class="detail-grid">
          <div><dt>实验 / 指标 / 窗口</dt><dd>{{ ticketDetail.实验编码 }} / {{ ticketDetail.指标编码 }} / {{ ticketDetail.检验窗口 }}</dd></div>
          <div><dt>适用口径版本</dt><dd>{{ ticketDetail.口径版本 }}</dd></div>
          <div><dt>登记样本版本</dt><dd>{{ ticketDetail.登记样本版本 ?? '—' }}</dd></div>
          <div><dt>实际样本版本 / 轮次</dt><dd>{{ ticketDetail.样本版本 ?? '待领取' }} / {{ ticketDetail.分配轮次 ?? '—' }}</dd></div>
          <div><dt>版本冲突</dt><dd>{{ ticketDetail.版本冲突 ? ticketDetail.冲突说明 : '无' }}</dd></div>
          <div><dt>工单状态</dt><dd>{{ ticketDetail.工单状态 }}</dd></div>
        </div>

        <h4 class="sub-title">重定位依据（实际检验 / 待处理状态）</h4>
        <pre class="json-box" data-testid="ticket-basis">{{ JSON.stringify(ticketDetail.冻结证据 ?? ticketDetail.当前依据, null, 2) }}</pre>

        <div class="page-actions">
          <button class="btn" type="button" @click="ticketDetail = null">关闭</button>
          <button
            v-if="ticketDetail.工单状态 === '检验中' && !ticketDetail.只读"
            class="btn primary"
            type="button"
            @click="onRecheck(ticketDetail.id, '无显著差异'); refreshTicket(ticketDetail.id)"
          >
            执行实际重检
          </button>
          <button
            v-if="ticketDetail.工单状态 === '待确认' && !ticketDetail.只读"
            class="btn primary"
            type="button"
            data-testid="close-ticket"
            @click="onCloseTicket(ticketDetail.id)"
          >
            办结并冻结证据
          </button>
          <button
            v-if="ticketDetail.工单状态 === '已办结'"
            class="btn primary"
            type="button"
            data-testid="submit-retro"
            @click="promptRetro(ticketDetail.id)"
          >
            提交运营复盘
          </button>
        </div>
      </div>
    </div>

    <!-- ============ 复盘只读对照弹窗 ============ -->
    <div v-if="retroDetail" class="modal-backdrop" data-testid="retro-modal">
      <div class="modal wide">
        <h3>复盘材料 {{ retroDetail.材料编号 }}（{{ retroDetail.status }}）</h3>
        <p class="muted">结论：{{ retroDetail.复盘结论 }}</p>
        <h4 class="sub-title">提交时冻结的证据版次（重检不改写）</h4>
        <pre class="json-box">{{ JSON.stringify(retroDetail.冻结证据, null, 2) }}</pre>
        <h4 class="sub-title">当前证据版次对照</h4>
        <pre class="json-box">{{ JSON.stringify(retroDetail.当前证据版次, null, 2) }}</pre>
        <div class="page-actions">
          <button class="btn" type="button" @click="retroDetail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  boardTriggerRecheck,
  claimTicket,
  closeTicket,
  confirmRetro,
  confirmSnapshot,
  evidenceBoard,
  executeRecheck,
  listClaimable,
  listExperiments,
  listRetros,
  listRuns,
  listSnapshots,
  listTickets,
  listWorkOrders,
  readRetro,
  submitRetro,
  submitTicket,
  ticketDetail as fetchTicketDetail,
  verifyWorkOrder,
} from '@/api/risk-patrol'
import type { EvidenceLine, PatrolTicket } from '@/api/risk-patrol'

type AnyRow = Record<string, string | number | boolean | null>

const activeTab = ref<'workbench' | 'claim' | 'evidence' | 'tickets' | 'retro'>('workbench')
const experiments = ref<AnyRow[]>([])
const snapshots = ref<AnyRow[]>([])
const claimable = ref<PatrolTicket[]>([])
const tickets = ref<PatrolTicket[]>([])
const workOrders = ref<AnyRow[]>([])
const retros = ref<AnyRow[]>([])
const runs = ref<AnyRow[]>([])

const evidenceExpCode = ref('E1')
const evidence = ref<Awaited<ReturnType<typeof evidenceBoard>> | null>(null)

const showSubmit = ref(false)
const submitForm = ref({ exp_code: '', metric_code: '', window: 'W1', remark: '' })
const ticketDetail = ref<(PatrolTicket & Record<string, unknown>) | null>(null)
const retroDetail = ref<AnyRow | null>(null)
const errorMessage = ref('')
const infoMessage = ref('')

const activeTickets = computed(() =>
  tickets.value.filter((t) => t.工单状态 === '检验中' || t.工单状态 === '待确认'),
)

const tabs = computed(() => [
  { key: 'workbench' as const, label: '巡检工作台', badge: 0 },
  { key: 'claim' as const, label: 'AA 领取与重检', badge: claimable.value.length },
  { key: 'evidence' as const, label: '异常实验证据', badge: 0 },
  { key: 'tickets' as const, label: '办理单与核对工单', badge: activeTickets.value.length },
  { key: 'retro' as const, label: '运营复盘', badge: 0 },
])

function formatShare(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) ? `${(num * 100).toFixed(1)}%` : '—'
}

function lineStatusClass(line: EvidenceLine): string {
  if (line.状态 === '缺项' || line.状态 === '待确认') return 'tag-danger'
  if (line.状态 === '已过期') return 'tag-expired'
  return 'tag-ok'
}

function flash(message: string, isError = false) {
  if (isError) {
    errorMessage.value = message
    infoMessage.value = ''
  } else {
    infoMessage.value = message
    errorMessage.value = ''
  }
}

async function guard(action: () => Promise<unknown>, okMessage: string) {
  try {
    await action()
    flash(okMessage)
    await reloadAll()
  } catch (error) {
    flash(error instanceof Error ? error.message : '操作失败', true)
  }
}

async function reloadAll() {
  try {
    const [expRes, snapRes, claimRes, ticketRes, woRes, retroRes, runRes] = await Promise.all([
      listExperiments(),
      listSnapshots(),
      listClaimable(),
      listTickets(),
      listWorkOrders(),
      listRetros(),
      listRuns(),
    ])
    experiments.value = expRes.items as AnyRow[]
    snapshots.value = snapRes.items as AnyRow[]
    claimable.value = claimRes.items
    tickets.value = ticketRes.items
    workOrders.value = woRes.items as AnyRow[]
    retros.value = retroRes.items as AnyRow[]
    runs.value = runRes.items as AnyRow[]
  } catch (error) {
    flash(error instanceof Error ? error.message : '工作台数据读取失败', true)
  }
}

function openSubmit(expCode: string, metricCode: string) {
  submitForm.value = { exp_code: expCode, metric_code: metricCode, window: 'W1', remark: '' }
  showSubmit.value = true
}

async function onSubmitTicket() {
  await guard(
    () => submitTicket({ ...submitForm.value }),
    '巡检办理单已开具（范围限指标与窗口，未锁样本版）',
  )
  showSubmit.value = false
}

function openEvidence(expCode: string) {
  evidenceExpCode.value = expCode
  activeTab.value = 'evidence'
  void loadEvidence()
}

async function loadEvidence() {
  if (!evidenceExpCode.value.trim()) {
    flash('请输入实验编码', true)
    return
  }
  try {
    evidence.value = await evidenceBoard(evidenceExpCode.value.trim())
    flash('')
  } catch (error) {
    evidence.value = null
    flash(error instanceof Error ? error.message : '证据看板读取失败', true)
  }
}

async function onClaim(id: number) {
  await guard(async () => {
    const res = await claimTicket(id)
    if (res.版本冲突) flash(res.message)
  }, '办理单已领取，实际检验轮次与样本版本已解析')
}

async function onRecheck(id: number, result: string) {
  await guard(() => executeRecheck(id, { result }), '一次实际重检已记录适用口径、分组与开单结果')
  if (ticketDetail.value?.id === id) {
    await refreshTicket(id)
  }
}

async function onVerifyWorkOrder(id: number) {
  await guard(() => verifyWorkOrder(id, '分组比例已人工核对确认'), '样本量核对工单已核对')
}

async function onCloseTicket(id: number) {
  await guard(() => closeTicket(id), '办理单已办结，证据版次已冻结，后续重检不改写本单')
  ticketDetail.value = null
}

async function openTicket(id: number) {
  try {
    const res = await fetchTicketDetail(id)
    ticketDetail.value = res.item as PatrolTicket & Record<string, unknown>
  } catch (error) {
    flash(error instanceof Error ? error.message : '巡检单读取失败', true)
  }
}

async function refreshTicket(id: number) {
  const res = await fetchTicketDetail(id)
  ticketDetail.value = res.item as PatrolTicket & Record<string, unknown>
}

function promptRetro(ticketId: number) {
  const summary = window.prompt('请输入运营复盘结论')
  if (!summary) return
  void guard(async () => {
    await submitRetro({ ticket_id: ticketId, summary })
    ticketDetail.value = null
  }, '复盘材料已提交并冻结当时证据版次')
}

async function onReadRetro(id: number) {
  try {
    const res = await readRetro(id)
    retroDetail.value = res.item as AnyRow
  } catch (error) {
    flash(error instanceof Error ? error.message : '复盘材料读取失败', true)
  }
}

async function onConfirmRetro(id: number) {
  await guard(() => confirmRetro(id), '复盘材料已确认，后续重检不会改写本材料')
}

// 看板触发重检入口保留给实验行快捷操作（新办一定使用当前确认版）。
async function onBoardTrigger(expCode: string, metricCode: string, window: string) {
  await guard(
    () => boardTriggerRecheck({ exp_code: expCode, metric_code: metricCode, window, result: '无显著差异' }),
    '看板已按当前确认版触发一次实际重新检验',
  )
}

// 分组更正：确认新样本版本（演示入口，旧版自动转过期）。
async function onConfirmSnapshot(expCode: string, allocRound: string, ctrl: number, treat: number) {
  await guard(
    () => confirmSnapshot({ exp_code: expCode, alloc_round: allocRound, ctrl_count: ctrl, treat_count: treat }),
    '新样本版本已确认，旧确认版已转过期',
  )
}

defineExpose({ onBoardTrigger, onConfirmSnapshot, runs })

onMounted(reloadAll)
</script>

<style scoped>
.tab-bar { display: flex; gap: 8px; margin: 8px 0 16px; flex-wrap: wrap; }
.tab-btn {
  border: 1px solid var(--border); background: #fff; border-radius: 8px;
  padding: 8px 14px; cursor: pointer; font-size: 13px;
}
.tab-btn.active { background: var(--brand); color: #fff; border-color: var(--brand); }
.tab-badge {
  display: inline-block; min-width: 18px; padding: 0 5px; margin-left: 6px;
  background: #b42318; color: #fff; border-radius: 999px; font-size: 11px; line-height: 18px;
}
.section-title { font-size: 15px; margin: 18px 0 8px; display: flex; gap: 10px; align-items: center; }
.muted { color: var(--muted); font-weight: 400; }
.small { font-size: 12px; }
.tag {
  display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px;
  border: 1px solid transparent; white-space: nowrap;
}
.tag-ok { background: #e7f6ec; color: #117a37; border-color: #b7e4c7; }
.tag-pending { background: #fff4e0; color: #b25e09; border-color: #ffd8a8; }
.tag-danger { background: #fde8e8; color: #b42318; border-color: #f5c2c2; }
.tag-expired { background: #eef1f5; color: #64748b; border-color: #d8dee6; }
.tag-missing { background: #fde8e8; color: #b42318; border-color: #f5c2c2; }
.evidence-card {
  border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-bottom: 14px; background: #fcfdff;
}
.evidence-head { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.sub-table { margin-top: 6px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 10px 0; }
.detail-grid dt { font-size: 12px; color: var(--muted); }
.detail-grid dd { margin: 2px 0 0; font-size: 13px; }
.sub-title { font-size: 13px; margin: 14px 0 6px; }
.json-box {
  background: #0f172a; color: #dbe4f0; border-radius: 8px; padding: 12px;
  font-size: 12px; overflow: auto; max-height: 240px;
}
.modal.wide { width: min(760px, 100%); }
.info-text { color: #117a37; font-size: 13px; }
</style>
