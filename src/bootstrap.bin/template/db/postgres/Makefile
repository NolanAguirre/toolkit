.DEFAULT_GOAL := help

help:
	@echo 'Database: __NAME__ (PostgreSQL, postgres@localhost:5432)'
	@echo '  init    Create the database on the existing shared server (fails if present)'
	@echo '  deploy  Deploy pending Sqitch changes to local'
	@echo '  status  Show Sqitch deployment status'
	@echo '  verify  Run empty Sqitch verification scripts (no schema assertions)'
	@echo '  revert  Refuse reversion; this database is forward-only'
	@echo '  help    Show this help'
	@echo 'Requires Sqitch with PostgreSQL support and PostgreSQL client tools.'
	@echo 'Configure credentials outside this repository, e.g. with .pgpass.'
	@echo 'Next change: v1.001.0 with [v1.000.0] in sqitch.plan; depend on the predecessor thereafter.'
	@echo 'Use transactional, idempotent deploy SQL and empty revert/verify files for every version.'

init:
	createdb --maintenance-db='__MAINTENANCE_URL__' __NAME__
