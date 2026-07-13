.PHONY: validate build up down doctor

validate:
	python3 scripts/validate_repo.py
	python3 -m compileall -q scripts
	bash -n scripts/start.sh

build:
	docker build --platform linux/amd64 -t ltx23-i2v-runpod:local .

up:
	docker compose up --build

down:
	docker compose down

doctor:
	docker compose exec comfyui python /opt/bootstrap/scripts/doctor.py \
		--manifest-root /opt/bootstrap/manifest \
		--data-root /workspace \
		--comfy-root /opt/ComfyUI \
		--profile "$${MODEL_PROFILE:-workflow}" \
		--server-url http://127.0.0.1:8188
