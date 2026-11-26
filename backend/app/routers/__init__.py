"""业务路由汇总：通用资源路由 + 风险巡检工作台专用路由。"""
from __future__ import annotations

from app.routers import resource, risk_patrol

# 专用路由含 /api/risk-patrol 固定前缀，先注册；
# 通用资源路由 /api/{module} 放最后，避免动态路径抢先匹配固定路径。
ROUTERS = [risk_patrol, resource]
