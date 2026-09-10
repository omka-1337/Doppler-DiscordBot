.PHONY: start stop update restart status logs ensure-env

ensure-env:
	@if [ ! -f .env ]; then \
		echo "No .env file found. Creating one from .env.example..."; \
		cp .env.example .env; \
		RANDOM_PASSWORD=$$(openssl rand -hex 16); \
		sed -i "s/LAVALINK_PASSWORD=/LAVALINK_PASSWORD=$$RANDOM_PASSWORD/" .env; \
		echo "Generated .env with a random LAVALINK_PASSWORD."; \
		echo ""; \
		echo "IMPORTANT: fill in DISCORD_BOT_TOKEN via web panel at http://localhost:8000 or http://your_home_server_adress:8000 once it's running."; \
		echo ""; \
	fi

start: ensure-env
		docker-compose up -d

stop:
		docker compose down

update: ensure-env
		docker compose stop
		@git fetch origin releases
		@# --ff-only rather than a plain pull: a deployment clone has no local
		@# commits to merge, so anything that cannot fast-forward means the
		@# published history moved and needs a deliberate reset, not a merge.
		@git merge --ff-only FETCH_HEAD || ( \
			echo ""; \
			echo "Cannot fast-forward: this clone has diverged from origin/releases."; \
			echo "Nothing here is meant to carry local commits, so the fix is:"; \
			echo ""; \
			echo "    git fetch origin && git reset --hard origin/releases"; \
			echo ""; \
			echo "Your .env, savedata/, secrets/ and installed plugins are gitignored"; \
			echo "and are not touched by that."; \
			echo ""; \
			exit 1 )
		docker compose up -d --build --remove-orphans
		docker image prune -f

restart:
		docker-compose restart

status:
		docker-compose ps

logs:
		docker-compose logs -f $(s)