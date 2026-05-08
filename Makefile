.PHONY: start handoff memory-check command-center daily-board autonomous autonomous-watch maintenance-autopilot client-billing personal-phone-queue intake-governor intake-governor-visual phone-app-intake ai-router autofox-rollout owner-pre-send-notice imessage-fallback highlevel-inbox-workaround webhook-probe inactive test

start:
	sh scripts/start-session.sh

handoff:
	sh scripts/finish-session.sh "$(MSG)"

memory-check:
	sh scripts/check-memory.sh

command-center:
	python3 scripts/fundz_command_center.py

daily-board:
	python3 scripts/fundz_command_center.py --limit 10
	@printf '\n'
	@sed -n '1,20p' data/local/command-center/fundz-daily-board.md

autonomous:
	FUNDZ_ALLOW_IMESSAGE_FALLBACK_LAUNCHAGENT=true python3 scripts/fundz_autonomous_operator.py --once --today "$${TODAY:-$$(date +%F)}" --run-tests

autonomous-watch:
	FUNDZ_ALLOW_IMESSAGE_FALLBACK_LAUNCHAGENT=true python3 scripts/fundz_autonomous_operator.py --watch --today "$${TODAY:-$$(date +%F)}"

maintenance-autopilot:
	python3 scripts/fundz_maintenance_autopilot.py --today "$${TODAY:-$$(date +%F)}" --run-tests

client-billing:
	python3 scripts/fundz_client_billing_lookup.py "$(CLIENT)"

personal-phone-queue:
	python3 scripts/fundz_personal_phone_message_queue.py

intake-governor:
	python3 scripts/fundz_intake_governor.py

intake-governor-visual:
	python3 scripts/fundz_intake_governor.py
	python3 scripts/fundz_intake_governor_visual.py

phone-app-intake:
	python3 scripts/fundz_phone_app_intake.py

ai-router:
	python3 scripts/fundz_ai_router.py --prompt "$(PROMPT)"

autofox-rollout:
	python3 scripts/fundz_autofox_rollout_packet.py

owner-pre-send-notice:
	python3 scripts/fundz_semi_autonomous_bot.py --owner-pre-send-notice --owner-pre-send-notice-live

imessage-fallback:
	python3 scripts/fundz_imessage_fallback.py

highlevel-inbox-workaround:
	python3 scripts/fundz_highlevel_inbox_poller.py --manual-import

webhook-probe:
	python3 scripts/fundz_credit_tracker_webhook_probe.py

inactive:
	sh scripts/fundz_inactive.sh

test:
	python3 -m unittest discover -s tests -q
