import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import RiskPatrolView from '@/views/RiskPatrolView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 风险巡检工作台为专用页面，须放在通用模块动态路由之前匹配。
    { path: '/risk_patrol', name: 'risk-patrol', component: RiskPatrolView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
