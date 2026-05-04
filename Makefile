.PHONY: start handoff memory-check

start:
	sh scripts/start-session.sh

handoff:
	sh scripts/finish-session.sh "$(MSG)"

memory-check:
	sh scripts/check-memory.sh
