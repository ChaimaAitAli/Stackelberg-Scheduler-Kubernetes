@echo off
setlocal enabledelayedexpansion

echo === KUBERNETES CLUSTER RESOURCE SUMMARY ===
echo.

echo 1. Node Overview:
kubectl get nodes -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory,KERNEL:.status.nodeInfo.kernelVersion

echo.
echo 2. Current Resource Usage:
kubectl top nodes 2>nul || echo Metrics server not available - install it with: kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

echo.
echo 3. Pod Resource Requests by Namespace:
kubectl get pods --all-namespaces -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,CPU_REQ:.spec.containers[*].resources.requests.cpu,MEM_REQ:.spec.containers[*].resources.requests.memory

echo.
echo 4. Total Allocatable Resources:
echo NODE              CPU     MEMORY
echo ----              ---     ------

set "total_cpu=0"
set "total_mem=0"

for /f "tokens=1-3" %%a in ('kubectl get nodes -o jsonpath^="{range .items[*]}{.metadata.name}{\"\t\"}{.status.allocatable.cpu}{\"\t\"}{.status.allocatable.memory}{\"\n\"}{end}"') do (
    set "node=%%a"
    set "cpu=%%b"
    set "mem=%%c"
    
    rem Convert CPU (could be in millicores)
    if "!cpu:~-1!"=="m" (
        set /a "cpu_val=!cpu:~0,-1! / 1000"
    ) else (
        set "cpu_val=!cpu!"
    )
    
    rem Convert memory to GB
    if "!mem:~-2!"=="Ki" (
        set /a "mem_val=!mem:~0,-2! / 1024 / 1024"
    ) else if "!mem:~-2!"=="Mi" (
        set /a "mem_val=!mem:~0,-2! / 1024"
    ) else if "!mem:~-2!"=="Gi" (
        set "mem_val=!mem:~0,-2!"
    ) else (
        set /a "mem_val=!mem! / 1024 / 1024 / 1024"
    )
    
    echo !node!          !cpu_val!     !mem_val! GB
    
    set /a "total_cpu=!total_cpu! + !cpu_val!"
    set /a "total_mem=!total_mem! + !mem_val!"
)

echo ----              ---     ------
echo TOTAL:            %total_cpu%     %total_mem% GB
echo.
echo Your minimum requirements from scheduler:
echo - Web App: 2.0 CPU, 8.0 GB
echo - Data Processing: 1.0 CPU, 4.0 GB
echo - ML Training: 4.0 CPU, 16.0 GB
echo - TOTAL MINIMUM: 7.0 CPU, 28.0 GB
echo.

if %total_cpu% geq 7.0 (
    if %total_mem% geq 28.0 (
        echo ✅ Your cluster has sufficient resources
    ) else (
        echo ❌ Your cluster may not have sufficient resources
        set /a "missing_cpu=7.0 - %total_cpu% > 0 ? 7.0 - %total_cpu% : 0"
        set /a "missing_mem=28.0 - %total_mem% > 0 ? 28.0 - %total_mem% : 0"
        echo    Missing: %missing_cpu% CPU, %missing_mem% GB memory
    )
) else (
    echo ❌ Your cluster may not have sufficient resources
    set /a "missing_cpu=7.0 - %total_cpu% > 0 ? 7.0 - %total_cpu% : 0"
    set /a "missing_mem=28.0 - %total_mem% > 0 ? 28.0 - %total_mem% : 0"
    echo    Missing: %missing_cpu% CPU, %missing_mem% GB memory
)

echo.
echo 5. Detailed Node Information:
echo Run 'kubectl describe nodes' for complete details

endlocal