.DEFAULT_GOAL := help
.PHONY: help start

help:
	@echo 'start   Start the repository OpenResty proxy on its allocated PORT'
	@echo '        Requires openresty, lua-resty-session 4.x, envdir and a running ../memcached'
	@echo '        Add location blocks in routes/*.conf; protect one with'
	@echo '        access_by_lua_block { require("session").require_session() }'
	@echo '        The session secret is created in .runtime/session_secret on first start'
	@echo 'help    Show commands'

start:
	envdir ./env-dir/default envdir "./env-dir/$${ENV_USER:-$${USER:-default}}" sh ./start
