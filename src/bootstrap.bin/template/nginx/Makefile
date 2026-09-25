.DEFAULT_GOAL := help
.PHONY: help start

help:
	@echo 'start   Start the repository UI/API nginx proxy on its allocated PORT'
	@echo '        Requires nginx and envdir; add location blocks in routes/*.conf'
	@echo '        Empty scaffolds return 404 until UI/API routes are added'
	@echo 'help    Show commands'

start:
	envdir ./env-dir/default envdir "./env-dir/$${ENV_USER:-$${USER:-default}}" sh ./start
