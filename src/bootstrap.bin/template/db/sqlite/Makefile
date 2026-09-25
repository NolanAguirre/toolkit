.DEFAULT_GOAL := help

help:
	@echo 'Database: __NAME__ (SQLite, db/__NAME__/__NAME__.sqlite from repository root)'
	@echo '  init    Create/update the SQLite database through Sqitch deploy'
	@echo '  deploy  Deploy pending Sqitch changes to local'
	@echo '  status  Show Sqitch deployment status'
	@echo '  verify  Run empty Sqitch verification scripts (no schema assertions)'
	@echo '  revert  Refuse reversion; this database is forward-only'
	@echo '  help    Show this help'
	@echo 'Requires Sqitch with SQLite support and the sqlite3 client.'
	@echo 'Next change: v1.001.0 with [v1.000.0] in sqitch.plan; depend on the predecessor thereafter.'
	@echo 'Use transactional, idempotent deploy SQL and empty revert/verify files for every version.'

init: deploy

