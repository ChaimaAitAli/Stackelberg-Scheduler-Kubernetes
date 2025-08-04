# Step 1: Go to API repo
cd stackelberg-scheduler-api

# Step 2: Create KinD cluster
kind create cluster --name stackelberg-cluster --config kind-config.yaml

# Step 3:  load API Docker image
kind load docker-image stackelberg-api:latest --name stackelberg-cluster

# Step 4: Deploy API service
kubectl apply -f deploy/api-service.yaml

# Step 5: Build and load Scheduler Docker image

kind load docker-image stackelberg-scheduler:v3 --name stackelberg-cluster

# Step 6: Apply RBAC, ConfigMap, and Deployment
kubectl apply -f deploy/.

Write-Host "✅ All components deployed successfully."
