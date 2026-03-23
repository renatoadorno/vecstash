.PHONY: install dev uninstall test clean bootstrap status daemon daemon-stop launchd-install launchd-uninstall

PROJECT_DIR := $(shell pwd)
PLIST_NAME  := com.vecstash.daemon
PLIST_SRC   := $(PROJECT_DIR)/support/$(PLIST_NAME).plist
PLIST_DST   := $(HOME)/Library/LaunchAgents/$(PLIST_NAME).plist
SOCKET_PATH := $(HOME)/.vecstash/daemon.sock
UID         := $(shell id -u)

# ── Install / Uninstall ─────────────────────────────────────────────

install:
	uv tool install $(PROJECT_DIR) --force
	@echo "Installed. Run 'make bootstrap' to download the embedding model."

dev:
	uv tool install -e $(PROJECT_DIR) --force
	@echo "Installed in editable mode."

uninstall: launchd-uninstall
	uv tool uninstall vecstash
	@echo "Uninstalled."

# ── Development ──────────────────────────────────────────────────────

test:
	uv run python -m unittest discover -s tests -p 'test_*.py'

clean:
	rm -rf dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ── Runtime ──────────────────────────────────────────────────────────

bootstrap:
	vecstash models bootstrap

status:
	vecstash status

daemon:
	vecstash-daemon

daemon-stop:
	@if [ -S "$(SOCKET_PATH)" ]; then \
		launchctl bootout gui/$(UID) $(PLIST_DST) 2>/dev/null || true; \
		rm -f "$(SOCKET_PATH)"; \
		echo "Daemon stopped."; \
	else \
		echo "Daemon is not running."; \
	fi

# ── launchd ──────────────────────────────────────────────────────────

launchd-install:
	@mkdir -p $(HOME)/Library/LaunchAgents
	sed 's|__HOME__|$(HOME)|g' $(PLIST_SRC) > $(PLIST_DST)
	launchctl bootstrap gui/$(UID) $(PLIST_DST)
	@echo "Daemon registered with launchd. It will start on login."

launchd-uninstall:
	@launchctl bootout gui/$(UID) $(PLIST_DST) 2>/dev/null || true
	@rm -f $(PLIST_DST)
	@echo "Daemon unregistered from launchd."
