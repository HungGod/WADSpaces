IMAGE ?= ghcr.io/wad/workspace-video-game-dev:latest
NAME  ?= ws-video-game-dev

build:
	docker build --network=host -t $(IMAGE) .

rebuild:
	docker build --network=host --no-cache -t $(IMAGE) .

run: 
	docker compose up -d

stop:
	docker compose down
