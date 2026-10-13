.DEFAULT_GOAL := help
.PHONY: help install build test start

help:
	@echo "install   Install dashboard and API dependencies"
	@echo "build     Build the dashboard"
	@echo "test      Test the API"
	@echo "start     Start the API and dashboard (logs in each directory)"

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
