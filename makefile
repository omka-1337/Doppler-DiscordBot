.PHONY: start stop update restart status logs

start:
		docker-compose up -d

stop:
		docker compose down

update:
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