# Sqitch database db/__NAME__
.PHONY: help db.__NAME__.help db.__NAME__.init db.__NAME__.deploy db.__NAME__.status db.__NAME__.verify db.__NAME__.revert

help: db.__NAME__.help

db.__NAME__.help:
	@echo 'db/__NAME__: db.__NAME__.init db.__NAME__.deploy db.__NAME__.status db.__NAME__.verify db.__NAME__.revert'
	@$(MAKE) --no-print-directory -C db/__NAME__ help

db.__NAME__.init:
	$(MAKE) -C db/__NAME__ init

db.__NAME__.deploy:
	$(MAKE) -C db/__NAME__ deploy

db.__NAME__.status:
	$(MAKE) -C db/__NAME__ status

db.__NAME__.verify:
	$(MAKE) -C db/__NAME__ verify

db.__NAME__.revert:
	$(MAKE) -C db/__NAME__ revert
