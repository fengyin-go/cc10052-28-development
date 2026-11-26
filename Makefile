.PHONY: install backend frontend test-backend typecheck-frontend

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm ci

backend:
	cd backend && ./run.sh

frontend:
	cd frontend && npm run dev

# 风险巡检工作台领域回归：仅依赖标准库，直接驱动 RiskPatrolService。
test-backend:
	cd backend && .venv/bin/python -m unittest tests.test_risk_patrol -v

typecheck-frontend:
	cd frontend && npm run typecheck
