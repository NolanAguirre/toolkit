.PHONY: deployment.help deployment.build deployment.package deployment.push deployment.install deployment.setup deployment.migrate deployment.activate deployment.start deployment.stop deployment.restart deployment.status deployment.deploy

help: deployment.help

deployment.help:
	$(MAKE) -C deployment help

deployment.build:
	$(MAKE) -C deployment build

deployment.package:
	$(MAKE) -C deployment package

deployment.push:
	$(MAKE) -C deployment push

deployment.install:
	$(MAKE) -C deployment install

deployment.setup:
	$(MAKE) -C deployment setup

deployment.migrate:
	$(MAKE) -C deployment migrate

deployment.activate:
	$(MAKE) -C deployment activate

deployment.start:
	$(MAKE) -C deployment start

deployment.stop:
	$(MAKE) -C deployment stop

deployment.restart:
	$(MAKE) -C deployment restart

deployment.status:
	$(MAKE) -C deployment status

deployment.deploy:
	$(MAKE) -C deployment deploy

