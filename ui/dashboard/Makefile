.DEFAULT_GOAL := help
.PHONY: help install build start

help:
	@echo "install   Install dependencies"
	@echo "build     Build production assets in dist/"
	@echo "start     Start Vite in the background (start.log)"
	@echo "help      Show this help message"

install:
	npm install

build:
	npm run build

start:
	nohup envdir "./env-dir/$${ENV_USER:-$$USER}" npm start >start.log 2>&1 </dev/null & echo "started in background, pid $$! (logs: start.log)"
