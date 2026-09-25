.PHONY: install install.js install.python build start consumer help

help:
	@echo "Available commands:"
	@echo "  install         Install node and python dependencies"
	@echo "  install.js      Install node dependencies only"
	@echo "  install.python  Create cli/.venv and install cli/requirements.txt"
	@echo "  build           Run the build script, if configured"
	@echo "  start           Start the service in the background"
	@echo "  consumer        Drain the filesystem queue in the foreground"
	@echo "  help            Show this help message"

install:
	npm install
	$(MAKE) install.python

install.js:
	npm install

install.python:
	python3 -m venv cli/.venv
	cli/.venv/bin/pip install --upgrade pip
	cli/.venv/bin/pip install -r cli/requirements.txt

build:
	npm run build --if-present

start:
	nohup envdir "./env-dir/$${ENV_USER:-$$USER}" npm start >start.log 2>&1 </dev/null & echo "started in background, pid $$! (logs: start.log)"

consumer:
	envdir "./env-dir/$${ENV_USER:-$$USER}" cli/.venv/bin/python3 cli/consumer.py
