.DEFAULT_GOAL := help
.PHONY: help start services.nginx.help services.nginx.start

help:
	@echo 'start                 Start the repository nginx proxy in the foreground'
	@echo 'services.nginx.start  Start the repository UI/API proxy'
	@echo 'services.nginx.help   Show nginx setup and route help'

start: services.nginx.start

services.nginx.help:
	$(MAKE) -C services/nginx help

services.nginx.start:
	$(MAKE) -C services/nginx start
