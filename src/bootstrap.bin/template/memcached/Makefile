.DEFAULT_GOAL := help
.PHONY: help start

help:
	@echo 'start   Start memcached in the foreground on its allocated HOST and PORT'
	@echo '        Requires memcached and envdir; OpenResty stores sessions here'
	@echo 'help    Show commands'

start:
	envdir ./env-dir/default envdir "./env-dir/$${ENV_USER:-$${USER:-default}}" sh -c 'exec memcached -l "$$HOST" -p "$$PORT"'
