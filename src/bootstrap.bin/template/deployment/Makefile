.DEFAULT_GOAL := help
RELEASE ?= $(shell date -u +%Y%m%dT%H%M%SZ)
export RELEASE
.PHONY: help build package push install setup migrate activate start stop restart status deploy

help:
	@echo 'deployment.help       Show deployment commands'
	@echo 'deployment.build      Build production assets locally'
	@echo 'deployment.package    Package built assets and server code; never local state'
	@echo 'deployment.push       Build, package and deploy to the registered remote'
	@echo 'deployment.install    Install host prerequisites (sudo)'
	@echo 'deployment.setup      Prepare application state and runners (sudo)'
	@echo 'deployment.migrate    Back up and deploy database migrations while stopped (sudo)'
	@echo 'deployment.activate   Activate this release while stopped (sudo)'
	@echo 'deployment.start      Start the active release and wait for health (sudo)'
	@echo 'deployment.stop       Stop services and keep them down (sudo)'
	@echo 'deployment.restart    Restart the active release and check health (sudo)'
	@echo 'deployment.status     Check application health (sudo)'
	@echo 'deployment.deploy     Install, setup, migrate, activate and start this copied release (sudo)'

# Implement build/package and each host action as small application-owned scripts.
# Copy files.sh, remote-host.sh and .host/validate from the toolkit when scaffolding.
# Package ../.release/<release>/<service>/run plus each service's runtime files.
# Remote calls the generated /var/service-dir/<repo>-<service>/bin/deploy commands.
# Host maintenance targets below are explicit app operations, not invoked by remote deploy.
build:
	./build

package:
	./package "$(RELEASE)"

push:
	$(MAKE) build
	$(MAKE) package
	remote deploy __REPO__ "../.release/$(RELEASE)"

install:
	./validate install

setup:
	./validate setup

migrate:
	./validate migrate

activate:
	./validate activate

start:
	./validate start

stop:
	./validate stop

restart:
	./validate restart

status:
	./validate status

deploy:
	./validate deploy
