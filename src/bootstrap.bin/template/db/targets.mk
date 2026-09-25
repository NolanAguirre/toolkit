.PHONY: help init deploy status verify revert

deploy:
	sqitch deploy --target local

status:
	sqitch status --target local

verify:
	sqitch verify --target local

revert:
	@echo 'error: forward-only migrations; append a corrective version instead of reverting' >&2
	@exit 1
