@echo off
setlocal EnableDelayedExpansion

REM Stackelberg Scheduler Setup Script for Windows Batch
REM Usage: setup.bat [setup|test|clean|delete-cluster]

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=setup"

echo 🚀 Setting up Stackelberg Scheduler for Kubernetes
echo ==================================================

REM Check prerequisites
:check_prerequisites
echo 📋 Checking prerequisites...

REM Check Docker
docker info >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker is not running. Please start Docker first.
    exit /b 1
)
echo ✅ Docker is running

REM Check kind
kind version >nul 2>&1
if errorlevel 1 (
    echo ❌ kind is not installed. Please install kind first.
    echo    Visit: https://kind.sigs.k8s.io/docs/user/quick-start/#installation
    exit /b 1
)
echo ✅ kind is available

REM Check kubectl
kubectl version --client >nul 2>&1
if errorlevel 1 (
    echo ❌ kubectl is not installed. Please install kubectl first.
    exit /b 1
)
echo ✅ kubectl is available

REM Check go
go version >nul 2>&1
if errorlevel 1 (
    echo ❌ Go is not installed. Please install Go 1.21+ first.
    exit /b 1
)
echo ✅ Go is available

echo ✅ All prerequisites met!
goto :action_handler

REM Create directory structure
:create_structure
echo 📁 Creating directory structure...
if not exist "pkg\plugins\stackelberg" mkdir "pkg\plugins\stackelberg"
if not exist "deploy" mkdir "deploy"
if not exist "examples" mkdir "examples"
echo ✅ Directory structure created!
goto :eof

REM Build scheduler
:build_scheduler
echo 🔨 Building Stackelberg scheduler...
go mod tidy
if errorlevel 1 (
    echo ❌ Failed to tidy go modules
    exit /b 1
)

docker build -t stackelberg-scheduler:latest .
if errorlevel 1 (
    echo ❌ Failed to build scheduler image
    exit /b 1
)
echo ✅ Scheduler built successfully!
goto :eof

REM Create kind cluster
:create_cluster
echo 🌐 Creating kind cluster...
kind get clusters 2>nul | findstr "stackelberg-cluster" >nul
if not errorlevel 1 (
    echo ⚠️  Cluster 'stackelberg-cluster' already exists. Skipping creation.
    goto :eof
)

kind create cluster --name stackelberg-cluster --config kind-config.yaml
if errorlevel 1 (
    echo ❌ Failed to create cluster
    exit /b 1
)
echo ✅ Kind cluster with 3 worker nodes created!
goto :eof

REM Load images
:load_images
echo 📦 Loading images into kind cluster...
kind load docker-image stackelberg-scheduler:latest --name stackelberg-cluster
if errorlevel 1 (
    echo ❌ Failed to load scheduler image
    exit /b 1
)
echo ✅ Scheduler image loaded!

REM Check if API image exists
docker images | findstr "stackelberg-api" >nul
if not errorlevel 1 (
    ccd
    echo ✅ API image loaded!
) else (
    echo ⚠️  Stackelberg API image not found. You'll need to build and load it separately.
)
goto :eof

REM Deploy resources
:deploy_resources
echo 🚀 Deploying Kubernetes resources...

kubectl apply -f deploy/rbac.yaml
if errorlevel 1 (
    echo ❌ Failed to apply RBAC
    exit /b 1
)
echo ✅ RBAC configured!

kubectl apply -f deploy/configmap.yaml
if errorlevel 1 (
    echo ❌ Failed to apply ConfigMap
    exit /b 1
)
echo ✅ ConfigMap created!

kubectl get deployment stackelberg-api -n kube-system >nul 2>&1
if not errorlevel 1 (
    echo ⚠️  API service already deployed
) else (
    kubectl apply -f deploy/api-service.yaml
    if errorlevel 1 (
        echo ❌ Failed to deploy API service
        exit /b 1
    )
    echo ✅ API service deployed!
)

kubectl apply -f deploy/deployment.yaml
if errorlevel 1 (
    echo ❌ Failed to deploy scheduler
    exit /b 1
)
echo ✅ Scheduler deployed!

echo ⏳ Waiting for scheduler to be ready...
kubectl wait --for=condition=available --timeout=300s deployment/stackelberg-scheduler -n kube-system
if errorlevel 1 (
    echo ❌ Scheduler failed to become ready
    exit /b 1
)
echo ✅ Scheduler is ready!
goto :eof

REM Verify deployment
:verify_deployment
echo 🔍 Verifying deployment...

echo Cluster nodes:
kubectl get nodes

echo.
echo Scheduler pods:
kubectl get pods -n kube-system -l app=stackelberg-scheduler

echo.
echo API pods:
kubectl get pods -n kube-system -l app=stackelberg-api

echo.
echo Recent events:
kubectl get events --sort-by=.metadata.creationTimestamp --tail=5

echo ✅ Deployment verification complete!
goto :eof

REM Test scheduler
:test_scheduler
echo 🧪 Testing scheduler with example pod...

REM Create test pod YAML
echo apiVersion: v1 > test-pod.yaml
echo kind: Pod >> test-pod.yaml
echo metadata: >> test-pod.yaml
echo   name: test-web-app >> test-pod.yaml
echo   namespace: default >> test-pod.yaml
echo   labels: >> test-pod.yaml
echo     tenant: web-app >> test-pod.yaml
echo     app: test-app >> test-pod.yaml
echo spec: >> test-pod.yaml
echo   schedulerName: stackelberg-scheduler >> test-pod.yaml
echo   containers: >> test-pod.yaml
echo   - name: test-container >> test-pod.yaml
echo     image: nginx:alpine >> test-pod.yaml
echo     resources: {} >> test-pod.yaml

kubectl apply -f test-pod.yaml
if errorlevel 1 (
    echo ❌ Failed to create test pod
    del test-pod.yaml
    exit /b 1
)

echo ⏳ Waiting for pod to be scheduled...
timeout /t 10 /nobreak >nul

echo.
echo Pod status:
kubectl get pod test-web-app -o wide

echo.
echo Pod resources:
kubectl get pod test-web-app -o jsonpath="{.spec.containers[0].resources}"

echo.
echo Pod annotations:
kubectl get pod test-web-app -o jsonpath="{.metadata.annotations}"

REM Clean up
kubectl delete pod test-web-app --ignore-not-found=true >nul 2>&1
del test-pod.yaml

echo ✅ Scheduler test complete!
goto :eof

REM Clean up resources
:clean_resources
echo 🧹 Cleaning up resources...

if exist "example-pods.yaml" kubectl delete -f example-pods.yaml --ignore-not-found=true >nul 2>&1
if exist "deployment.yaml" kubectl delete -f deployment.yaml --ignore-not-found=true >nul 2>&1
if exist "api-service.yaml" kubectl delete -f api-service.yaml --ignore-not-found=true >nul 2>&1
if exist "configmap.yaml" kubectl delete -f configmap.yaml --ignore-not-found=true >nul 2>&1
if exist "rbac.yaml" kubectl delete -f rbac.yaml --ignore-not-found=true >nul 2>&1

echo ✅ Resources cleaned up!
goto :eof

REM Delete cluster
:delete_cluster
echo 🗑️  Deleting kind cluster...
kind delete cluster --name stackelberg-cluster
if errorlevel 1 (
    echo ❌ Failed to delete cluster
    exit /b 1
)
echo ✅ Cluster deleted!
goto :eof

REM Main setup function
:main_setup
echo Starting setup process...

call :create_structure
call :build_scheduler
call :create_cluster
call :load_images
call :deploy_resources
call :verify_deployment

echo.
echo 🎉 Stackelberg Scheduler setup complete!
echo.
echo Next steps:
echo 1. Deploy your Stackelberg API service if not already done
echo 2. Test with example pods: kubectl apply -f example-pods.yaml
echo 3. Monitor scheduler logs: kubectl logs -n kube-system -l app=stackelberg-scheduler -f
echo 4. Check resource allocations: kubectl get pods -o custom-columns="NAME:.metadata.name,CPU:.spec.containers[0].resources.requests.cpu,MEMORY:.spec.containers[0].resources.requests.memory"
echo.
echo For debugging: kubectl describe pod ^<pod-name^>
echo For scheduler events: kubectl get events --field-selector reason=Scheduled
goto :eof

REM Action handler
:action_handler
if "%ACTION%"=="setup" (
    call :main_setup
) else if "%ACTION%"=="test" (
    call :test_scheduler
) else if "%ACTION%"=="clean" (
    call :clean_resources
) else if "%ACTION%"=="delete-cluster" (
    call :delete_cluster
) else (
    echo Usage: setup.bat [setup^|test^|clean^|delete-cluster]
    echo   setup ^(default^) - Full setup process
    echo   test             - Test scheduler with example pod
    echo   clean            - Remove deployed resources
    echo   delete-cluster   - Delete the kind cluster
    exit /b 1
)

endlocal