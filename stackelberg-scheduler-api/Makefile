# Makefile for Stackelberg Scheduler

# Variables
SCHEDULER_IMAGE = stackelberg-scheduler:latest
API_IMAGE = stackelberg-api:latest
KIND_CLUSTER_NAME = stackelberg-cluster

# Default target
.PHONY: all
all: build-scheduler load-images deploy

# Build the scheduler binary
.PHONY: build
build:
	go mod tidy
	CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o stackelberg-scheduler .

# Build Docker image for scheduler
.PHONY: build-scheduler
build-scheduler:
	docker build -t $(SCHEDULER_IMAGE) .

# Build Docker image for API (assuming you have the API Dockerfile)
.PHONY: build-api
build-api:
	docker build -t $(API_IMAGE) -f api/Dockerfile api/

# Create kind cluster with 3 worker nodes
.PHONY: create-cluster
create-cluster:
	kind create cluster --name $(KIND_CLUSTER_NAME) --config kind-config.yaml

# Load images into kind cluster
.PHONY: load-images
load-images:
	kind load docker-image $(SCHEDULER_IMAGE) --name $(KIND_CLUSTER_NAME)
	@if docker images | grep -q "stackelberg-api"; then \
		kind load docker-image $(API_IMAGE) --name $(KIND_CLUSTER_NAME); \
		echo "API image loaded"; \
	fi

# Deploy all resources
.PHONY: deploy
deploy:
	kubectl apply -f rbac.yaml
	kubectl apply -f configmap.yaml
	kubectl apply -f api-service.yaml
	kubectl apply -f deployment.yaml

# Deploy example pods
.PHONY: deploy-examples
deploy-examples:
	kubectl apply -f example-pods.yaml

# Check scheduler status
.PHONY: status
status:
	@echo "=== Cluster Nodes ==="
	kubectl get nodes -o wide
	@echo ""
	@echo "=== Scheduler Pods ==="
	kubectl get pods -n kube-system -l app=stackelberg-scheduler
	@echo ""
	@echo "=== API Pods ==="
	kubectl get pods -n kube-system -l app=stackelberg-api

# View scheduler logs
.PHONY: logs-scheduler
logs-scheduler:
	kubectl logs -n kube-system -l app=stackelberg-scheduler -f

# View API logs
.PHONY: logs-api
logs-api:
	kubectl logs -n kube-system -l app=stackelberg-api -f

# Test the setup
.PHONY: test
test:
	kubectl apply -f example-pods.yaml
	sleep 10
	kubectl get pods -o wide
	kubectl describe pods

# Clean up
.PHONY: clean
clean:
	kubectl delete -f example-pods.yaml --ignore-not-found=true
	kubectl delete -f deployment.yaml --ignore-not-found=true
	kubectl delete -f api-service.yaml --ignore-not-found=true
	kubectl delete -f configmap.yaml --ignore-not-found=true
	kubectl delete -f rbac.yaml --ignore-not-found=true

# Delete kind cluster
.PHONY: delete-cluster
delete-cluster:
	kind delete cluster --name $(KIND_CLUSTER_NAME)

# Full setup for development with 3 worker nodes
.PHONY: dev-setup
dev-setup: create-cluster build-scheduler build-api load-images deploy
	@echo "Development environment ready with 3 worker nodes!"
	@echo "Cluster nodes:"
	@kubectl get nodes
	@echo ""
	@echo "To test: make deploy-examples"
	@echo "To check logs: make logs-scheduler"

# PowerShell setup (Windows users)
.PHONY: ps-setup
ps-setup:
	powershell -ExecutionPolicy Bypass -File setup.ps1 setup

# PowerShell test
.PHONY: ps-test
ps-test:
	powershell -ExecutionPolicy Bypass -File setup.ps1 test

# PowerShell clean
.PHONY: ps-clean
ps-clean:
	powershell -ExecutionPolicy Bypass -File setup.ps1 clean

# Rebuild and redeploy scheduler only
.PHONY: redeploy-scheduler
redeploy-scheduler: build-scheduler
	kind load docker-image $(SCHEDULER_IMAGE) --name $(KIND_CLUSTER_NAME)
	kubectl rollout restart deployment/stackelberg-scheduler -n kube-system
	kubectl rollout status deployment/stackelberg-scheduler -n kube-system

# Show resource allocations across all nodes
.PHONY: show-allocations
show-allocations:
	@echo "=== Pod Resource Allocations ==="
	kubectl get pods -o custom-columns="NAME:.metadata.name,NODE:.spec.nodeName,TENANT:.metadata.labels.tenant,CPU_REQ:.spec.containers[0].resources.requests.cpu,MEM_REQ:.spec.containers[0].resources.requests.memory,CPU_LIM:.spec.containers[0].resources.limits.cpu,MEM_LIM:.spec.containers[0].resources.limits.memory"

# Show cluster resource utilization
.PHONY: show-cluster-resources
show-cluster-resources:
	@echo "=== Cluster Resource Utilization ==="
	kubectl top nodes || echo "Metrics server not available"
	@echo ""
	@echo "=== Node Allocatable Resources ==="
	kubectl get nodes -o custom-columns="NAME:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory"

# Debug scheduler
.PHONY: debug
debug:
	@echo "=== Cluster Overview ==="
	kubectl get nodes
	@echo ""
	@echo "=== Scheduler Pod Status ==="
	kubectl get pods -n kube-system -l app=stackelberg-scheduler
	@echo ""
	@echo "=== API Pod Status ==="
	kubectl get pods -n kube-system -l app=stackelberg-api
	@echo ""
	@echo "=== Recent Events ==="
	kubectl get events --sort-by=.metadata.creationTimestamp --tail=10
	@echo ""
	@echo "=== Scheduler Logs (last 20 lines) ==="
	kubectl logs -n kube-system -l app=stackelberg-scheduler --tail=20

# Help
.PHONY: help
help:
	@echo "Available targets:"
	@echo "  all              - Build and deploy everything"
	@echo "  build            - Build scheduler binary"
	@echo "  build-scheduler  - Build scheduler Docker image"
	@echo "  build-api        - Build API Docker image"
	@echo "  create-cluster   - Create kind cluster with 3 worker nodes"
	@echo "  load-images      - Load images into kind cluster"
	@echo "  deploy           - Deploy scheduler and API"
	@echo "  deploy-examples  - Deploy example pods"
	@echo "  status           - Check deployment status"
	@echo "  logs-scheduler   - View scheduler logs"
	@echo "  logs-api         - View API logs"
	@echo "  test             - Deploy examples and check results"
	@echo "  clean            - Remove all deployed resources"
	@echo "  delete-cluster   - Delete kind cluster"
	@echo "  dev-setup        - Full development environment setup"
	@echo "  ps-setup         - PowerShell setup (Windows)"
	@echo "  ps-test          - PowerShell test (Windows)"
	@echo "  ps-clean         - PowerShell clean (Windows)"
	@echo "  redeploy-scheduler - Rebuild and redeploy scheduler"
	@echo "  show-allocations - Show pod resource allocations"
	@echo "  show-cluster-resources - Show cluster resource utilization"
	@echo "  debug            - Show debug information"
	@echo "  help             - Show this help message"