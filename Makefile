# Easy start: `make dev` runs Postgres + Django (:8001) + Vite (:5173).
SHELL := bash
-include .env
export

PY := $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python,.venv/bin/python)

.PHONY: dev setup db migrate backend frontend test e2e build

dev: db migrate
	trap 'kill 0' EXIT; $(PY) manage.py runserver 127.0.0.1:8001 & (cd frontend && npm run dev)

setup:
	python -m venv .venv
	$(PY) -m pip install -r requirements.txt
	cd frontend && npm install

db:
	docker compose up -d --wait

migrate:
	$(PY) manage.py migrate

backend: db migrate
	$(PY) manage.py runserver 127.0.0.1:8001

frontend:
	cd frontend && npm run dev

test:
	$(PY) manage.py test tracker
	cd frontend && npm run lint

e2e:
	$(PY) e2e_test.py

build:
	cd frontend && npm run build
