# Stackelberg Scheduler Setup Script for PowerShell
param(
    [Parameter(Position=0)]
    [ValidateSet("setup", "test", "clean", "delete-cluster")]
    [string]$Action = "setup"
)

$ErrorActionPreference = "Stop"

Write-Host "🚀 Setting up Stackelberg Scheduler for Kubernetes" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green

# Check prerequisites
function Test-Prerequisites {
    Write-Host "📋 Checking prerequisites..." -ForegroundColor Yellow
    
    # Check if Docker is running
    try {
        docker info | Out-Null
        Write-Host "✅ Docker is running" -ForegroundColor Green
    }
    catch {
        Write-Host "❌ Docker is not running. Please start Docker first." -ForegroundColor Red
        exit 1
    }
    
    # Check if kind is installed
    if (-not (Get-Command kind -ErrorAction SilentlyContinue)) {
        Write-Host "❌ kind is not installed. Please install kind first." -ForegroundColor Red
        Write-Host "   Visit: https://kind.sigs.k8s.io/docs/user/quick-start/#installation" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "✅ kind is available" -ForegroundColor Green
    
    # Check if kubectl is installed
    if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
        Write-Host "❌ kubectl is not installed. Please install kubectl first." -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ kubectl is available" -ForegroundColor Green
    
    # Check if go is installed
    if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
        Write-Host "❌ Go is not installed. Please install Go 1.21+ first." -ForegroundColor Red
        exit 1
    }
    
    $goVersion = go version
    Write-Host "✅ Go is available: $goVersion" -ForegroundColor Green
    
    Write-Host "✅ All prerequisites met!" -ForegroundColor Green
}

# Create directory structure
function New-DirectoryStructure {
    Write-Host "📁 Creating directory structure..." -ForegroundColor Yellow
    
    $directories = @("pkg\plugins\stackelberg", "deploy", "examples")
    foreach ($dir in $directories) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }
    
    Write-Host "✅ Directory structure created!" -ForegroundColor Green
}

# Build the scheduler
function Build-Scheduler {
    Write-Host "🔨 Building Stackelberg scheduler..." -ForegroundColor Yellow
    
    try {
        go mod tidy
        docker build -t stackelberg-scheduler:latest .
        Write-Host "✅ Scheduler built successfully!" -ForegroundColor Green
    }
    catch {
        Write-Host "❌ Failed to build scheduler: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# Create kind cluster
function New-KindCluster {
    Write-Host "🌐 Creating kind cluster..." -ForegroundColor Yellow
    
    $existingClusters = kind get clusters 2>$null
    if ($existingClusters -contains "stackelberg-cluster") {
        Write-Host "⚠️  Cluster 'stackelberg-cluster' already exists. Skipping creation." -ForegroundColor Yellow
    }
    else {
        try {
            kind create cluster --name stackelberg-cluster --config kind-config.yaml
            Write-Host "✅ Kind cluster created!" -ForegroundColor Green
        }
        catch {
            Write-Host "❌ Failed to create cluster: $($_.Exception.Message)" -ForegroundColor Red
            exit 1
        }
    }
}

# Load images
function Import-Images {
    Write-Host "📦 Loading images into kind cluster..." -ForegroundColor Yellow
    
    try {
        kind load docker-image stackelberg-scheduler:latest --name stackelberg-cluster
        Write-Host "✅ Scheduler image loaded into cluster!" -ForegroundColor Green
        
        # Check if API image exists
        $apiImageExists = docker images --format "table {{.Repository}}" | Select-String "stackelberg-api"
        if ($apiImageExists) {
            kind load docker-image stackelberg-api:latest --name stackelberg-cluster
            Write-Host "✅ API image loaded into cluster!" -ForegroundColor Green
        }
        else {
            Write-Host "⚠️  Stackelberg API image not found. You'll need to build and load it separately." -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "❌ Failed to load images: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# Deploy resources
function Deploy-Resources {
    Write-Host "🚀 Deploying Kubernetes resources..." -ForegroundColor Yellow
    
    try {
        # Apply RBAC
        kubectl apply -f rbac.yaml
        Write-Host "✅ RBAC configured!" -ForegroundColor Green
        
        # Apply ConfigMap
        kubectl apply -f configmap.yaml
        Write-Host "✅ ConfigMap created!" -ForegroundColor Green
        
        # Deploy API service (if available)
        $apiDeploymentExists = kubectl get deployment stackelberg-api -n kube-system 2>$null
        if ($apiDeploymentExists) {
            Write-Host "⚠️  API service already deployed" -ForegroundColor Yellow
        }
        else {
            kubectl apply -f api-service.yaml
            Write-Host "✅ API service deployed!" -ForegroundColor Green
        }
        
        # Deploy scheduler
        kubectl apply -f deployment.yaml
        Write-Host "✅ Scheduler deployed!" -ForegroundColor Green
        
        # Wait for scheduler to be ready
        Write-Host "⏳ Waiting for scheduler to be ready..." -ForegroundColor Yellow
        kubectl wait --for=condition=available --timeout=300s deployment/stackelberg-scheduler -n kube-system
        Write-Host "✅ Scheduler is ready!" -ForegroundColor Green
    }
    catch {
        Write-Host "❌ Failed to deploy resources: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# Verify deployment
function Test-Deployment {
    Write-Host "🔍 Verifying deployment..." -ForegroundColor Yellow
    
    Write-Host "Scheduler pods:" -ForegroundColor Cyan
    kubectl get pods -n kube-system -l app=stackelberg-scheduler
    
    Write-Host "`nAPI pods:" -ForegroundColor Cyan
    kubectl get pods -n kube-system -l app=stackelberg-api
    
    Write-Host "`nNodes:" -ForegroundColor Cyan
    kubectl get nodes
    
    Write-Host "`nRecent events:" -ForegroundColor Cyan
    kubectl get events --sort-by=.metadata.creationTimestamp --tail=5
    
    Write-Host "✅ Deployment verification complete!" -ForegroundColor Green
}

# Test with example pod
function Test-Scheduler {
    Write-Host "🧪 Testing scheduler with example pod..." -ForegroundColor Yellow

    # Create a test pod
    $testPodYaml = @"
apiVersion: v1
kind: Pod
metadata:
  name: test-web-app
  namespace: default
  labels:
    tenant: web-app
    app: test-app
spec:
  schedulerName: stackelberg-scheduler
  containers:
  - name: test-container
    image: nginx:alpine
    resources: {}
"@

    try {
        $testPodYaml | kubectl apply -f -

        # Wait a moment for scheduling
        Write-Host "Waiting for pod to be scheduled..." -ForegroundColor Yellow
        Start-Sleep -Seconds 10

        # Check if pod was scheduled and resources were assigned
        Write-Host "`nPod status:" -ForegroundColor Cyan
        kubectl get pod test-web-app -o wide

        Write-Host "`nPod resources:" -ForegroundColor Cyan
        $resources = kubectl get pod test-web-app -o jsonpath='{.spec.containers[0].resources}'
        if ($resources) {
            $resources | ConvertFrom-Json | ConvertTo-Json -Depth 3
        }

        Write-Host "`nPod annotations:" -ForegroundColor Cyan
        $annotations = kubectl get pod test-web-app -o jsonpath='{.metadata.annotations}'
        if ($annotations) {
            $annotations | ConvertFrom-Json | ConvertTo-Json -Depth 3
        }

        # Clean up test pod
        kubectl delete pod test-web-app --ignore-not-found=true | Out-Null

        Write-Host "✅ Scheduler test complete!" -ForegroundColor Green
    }
    catch {
        Write-Host "❌ Test failed: $($_.Exception.Message)" -ForegroundColor Red
        # Clean up on failure
        kubectl delete pod test-web-app --ignore-not-found=true | Out-Null
    }
}

# Clean up resources
function Remove-Resources {
    Write-Host "🧹 Cleaning up resources..." -ForegroundColor Yellow
    
    $resources = @(
        "example-pods.yaml",
        "deployment.yaml", 
        "api-service.yaml",
        "configmap.yaml",
        "rbac.yaml"
    )
    
    foreach ($resource in $resources) {
        if (Test-Path $resource) {
            kubectl delete -f $resource --ignore-not-found=true | Out-Null
        }
    }
    
    Write-Host "✅ Resources cleaned up!" -ForegroundColor Green
}

# Delete kind cluster
function Remove-KindCluster {
    Write-Host "🗑️  Deleting kind cluster..." -ForegroundColor Yellow
    
    try {
        kind delete cluster --name stackelberg-cluster
        Write-Host "✅ Cluster deleted!" -ForegroundColor Green
    }
    catch {
        Write-Host "❌ Failed to delete cluster: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Main setup function
function Start-Setup {
    Write-Host "Starting setup process..." -ForegroundColor Green
    
    Test-Prerequisites
    New-DirectoryStructure
    Build-Scheduler
    New-KindCluster
    Import-Images
    Deploy-Resources
    Test-Deployment
    
    Write-Host ""
    Write-Host "🎉 Stackelberg Scheduler setup complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "1. Deploy your Stackelberg API service if not already done" -ForegroundColor White
    Write-Host "2. Test with example pods: kubectl apply -f example-pods.yaml" -ForegroundColor White
    Write-Host "3. Monitor scheduler logs: kubectl logs -n kube-system -l app=stackelberg-scheduler -f" -ForegroundColor White
    Write-Host "4. Check resource allocations: kubectl get pods -o custom-columns='NAME:.metadata.name,CPU:.spec.containers[0].resources.requests.cpu,MEMORY:.spec.containers[0].resources.requests.memory'" -ForegroundColor White
    Write-Host ""
    Write-Host "For debugging: kubectl describe pod <pod-name>" -ForegroundColor Cyan
    Write-Host "For scheduler events: kubectl get events --field-selector reason=Scheduled" -ForegroundColor Cyan
}

# Main execution based on parameter
switch ($Action) {
    "setup" {
        Start-Setup
    }
    "test" {
        Test-Scheduler
    }
    "clean" {
        Remove-Resources
    }
    "delete-cluster" {
        Remove-KindCluster
    }
    default {
        Write-Host "Usage: .\setup.ps1 [setup|test|clean|delete-cluster]" -ForegroundColor Yellow
        Write-Host "  setup (default) - Full setup process" -ForegroundColor White
        Write-Host "  test           - Test scheduler with example pod" -ForegroundColor White
        Write-Host "  clean          - Remove deployed resources" -ForegroundColor White
        Write-Host "  delete-cluster - Delete the kind cluster" -ForegroundColor White
        exit 1
    }
}