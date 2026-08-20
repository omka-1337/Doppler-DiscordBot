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
		git pull origin main
		docker compose up -d --build
		docker image prune -f

restart:
		docker-compose restart

status:
		docker-compose ps

logs:
		docker-compose logs -f $(s)