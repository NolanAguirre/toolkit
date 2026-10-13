.DEFAULT_GOAL := help
.PHONY: help install build test start services.nginx.help services.nginx.start

help:
	@echo "install   Install dashboard and API dependencies"
	@echo "build     Build the dashboard"
	@echo "test      Test the API"
	@echo "start     Start API and dashboard in the background, then nginx in the foreground"
	@echo "          Open http://localhost:6760/dashboard/"
	@echo "services.nginx.start  Start only the nginx proxy in the foreground"
	@echo "services.nginx.help   Show nginx setup and route help"

install:
	$(MAKE) -C services/api install
	$(MAKE) -C ui/dashboard install

build:
	$(MAKE) -C ui/dashboard build

test:
	npm --prefix services/api test

start:
	$(MAKE) -C services/api start
	$(MAKE) -C ui/dashboard start
	$(MAKE) -C services/nginx start

services.nginx.help:
	$(MAKE) -C services/nginx help

services.nginx.start:
	$(MAKE) -C services/nginx start
