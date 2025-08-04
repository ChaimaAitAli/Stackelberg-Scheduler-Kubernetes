package stackelberg

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"
	"io/ioutil"
	"os"


	appsv1 "k8s.io/api/apps/v1"
	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/klog/v2"
	"k8s.io/kubernetes/pkg/scheduler/framework"
)

const (
	Name = "stackelberg-scheduler"
	
	// Tenant labels
	TenantLabel          = "tenant"
	WebAppTenant         = "web-app"
	DataProcessingTenant = "data-processing"
	MLTrainingTenant     = "ml-training"
	
	// API endpoint
	DefaultAPIEndpoint = "http://localhost:5000/stackelberg/allocate"
	
	// Annotations for tracking allocations
	AnnotationCPUAllocated     = "stackelberg.scheduler/cpu-allocated"
	AnnotationMemoryAllocated  = "stackelberg.scheduler/memory-allocated"
	AnnotationReplicas         = "stackelberg.scheduler/replicas"
	AnnotationAllocationApplied = "stackelberg.scheduler/allocation-applied"
	
	// Default desired replicas for each tenant
	DefaultWebAppReplicas         = 5
	DefaultDataProcessingReplicas = 4
	DefaultMLTrainingReplicas     = 3
)

type StackelbergPlugin struct {
	handle framework.Handle
	apiURL string
	client *http.Client
}

type StackelbergArgs struct {
	metav1.TypeMeta `json:",inline"`
	APIEndpoint     string `json:"apiEndpoint,omitempty"`
}

type APIRequest struct {
	TotalCPU    float64            `json:"total_cpu"`
	TotalMemory float64            `json:"total_memory"`
	Params      map[string]float64 `json:"params"`
}

type TenantAllocation struct {
	Tenant           string  `json:"tenant"`
	CPUPerReplica    float64 `json:"cpu_per_replica"`
	MemoryPerReplica float64 `json:"memory_per_replica"`
	Replicas         int     `json:"replicas"`
}

type APIResponse struct {
	Allocations      []TenantAllocation `json:"allocations"`
	Prices           struct {
		CPU    float64 `json:"cpu"`
		Memory float64 `json:"memory"`
	} `json:"prices"`
	PlatformUtility float64 `json:"platform_utility"`
	Converged       bool    `json:"converged"`
}

func (in *StackelbergArgs) DeepCopyObject() runtime.Object {
	if c := in.DeepCopy(); c != nil {
		return c
	}
	return nil
}

func (in *StackelbergArgs) DeepCopy() *StackelbergArgs {
	if in == nil {
		return nil
	}
	out := new(StackelbergArgs)
	*out = *in
	out.TypeMeta = in.TypeMeta
	return out
}

func New(obj runtime.Object, h framework.Handle) (framework.Plugin, error) {
	apiURL := "http://stackelberg-api-service.kube-system:5000/stackelberg/allocate"
	timeout := 30
	
	if obj != nil {
		klog.V(4).Infof("Received args object of type: %T", obj)
		if unknown, ok := obj.(*runtime.Unknown); ok {
			klog.V(4).Infof("Got runtime.Unknown with raw data: %s", string(unknown.Raw))
		}
	}

	klog.Infof("Stackelberg scheduler initialized with API URL: %s, timeout: %ds", apiURL, timeout)

	return &StackelbergPlugin{
		handle: h,
		apiURL: apiURL,
		client: &http.Client{
			Timeout: time.Duration(timeout) * time.Second,
		},
	}, nil
}

func (sp *StackelbergPlugin) Name() string {
	return Name
}

func (sp *StackelbergPlugin) PreFilter(ctx context.Context, state *framework.CycleState, pod *v1.Pod) (*framework.PreFilterResult, *framework.Status) {
	klog.V(4).Infof("PreFilter called for pod %s/%s", pod.Namespace, pod.Name)

	// Check if pod has tenant label
	tenant, exists := pod.Labels[TenantLabel]
	if !exists {
		klog.V(4).Infof("Pod %s/%s has no tenant label, skipping Stackelberg allocation", pod.Namespace, pod.Name)
		return nil, framework.NewStatus(framework.Success, "")
	}

	// Validate tenant type
	if !isValidTenant(tenant) {
		klog.Warningf("Pod %s/%s has invalid tenant label: %s", pod.Namespace, pod.Name, tenant)
		return nil, framework.NewStatus(framework.UnschedulableAndUnresolvable, fmt.Sprintf("invalid tenant: %s", tenant))
	}

	// Check if allocation was already applied to avoid redundant API calls
	if pod.Annotations[AnnotationAllocationApplied] == "true" {
		klog.V(4).Infof("Pod %s/%s already has allocation applied, skipping", pod.Namespace, pod.Name)
		return nil, framework.NewStatus(framework.Success, "")
	}

	// Get cluster resources
	nodes, err := sp.handle.ClientSet().CoreV1().Nodes().List(ctx, metav1.ListOptions{})
	if err != nil {
		klog.Errorf("Failed to list nodes: %v", err)
		return nil, framework.NewStatus(framework.Error, fmt.Sprintf("failed to list nodes: %v", err))
	}

	totalCPU, totalMemory := sp.calculateClusterResources(nodes.Items)
	klog.V(4).Infof("Cluster resources: CPU=%v, Memory=%v", totalCPU, totalMemory)

	// Get current pod counts for each tenant
	podCounts, err := sp.getTenantPodCounts(ctx)
	if err != nil {
		klog.Errorf("Failed to get tenant pod counts: %v", err)
		return nil, framework.NewStatus(framework.Error, fmt.Sprintf("failed to get tenant pod counts: %v", err))
	}

	// Prepare API request
	apiReq := sp.prepareAPIRequest(totalCPU, totalMemory, podCounts)

	// Call Stackelberg API
	apiResp, err := sp.callStackelbergAPI(apiReq)
	if err != nil {
		klog.Errorf("Failed to call Stackelberg API: %v", err)
		return nil, framework.NewStatus(framework.Error, fmt.Sprintf("Stackelberg API call failed: %v", err))
	}

	// Find allocation for current pod's tenant
	allocation := sp.findTenantAllocation(apiResp.Allocations, tenant)
	if allocation == nil {
		klog.Warningf("No allocation found for tenant %s", tenant)
		return nil, framework.NewStatus(framework.UnschedulableAndUnresolvable, fmt.Sprintf("no allocation found for tenant: %s", tenant))
	}

	// Update pod's resource requirements
	err = sp.updatePodResources(pod, allocation)
	if err != nil {
		klog.Errorf("Failed to update pod resources: %v", err)
		return nil, framework.NewStatus(framework.Error, fmt.Sprintf("failed to update pod resources: %v", err))
	}

	// Handle replica scaling asynchronously to avoid blocking scheduling
	// Use a background context to avoid cancellation issues
	go sp.handleReplicaScaling(context.Background(), tenant, allocation, pod.Namespace)

	klog.V(2).Infof("Updated pod %s/%s resources: CPU=%v, Memory=%v, target replicas=%d", 
		pod.Namespace, pod.Name, 
		allocation.CPUPerReplica, allocation.MemoryPerReplica, allocation.Replicas)

	return nil, framework.NewStatus(framework.Success, "")
}

func (sp *StackelbergPlugin) PreFilterExtensions() framework.PreFilterExtensions {
	return nil
}
func loadParamsFromConfig(path string) (map[string]float64, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("failed to open config file: %v", err)
	}
	defer file.Close()

	bytes, err := ioutil.ReadAll(file)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %v", err)
	}

	var params map[string]float64
	if err := json.Unmarshal(bytes, &params); err != nil {
		return nil, fmt.Errorf("failed to parse config JSON: %v", err)
	}
	return params, nil
}

// handleReplicaScaling manages the creation/scaling of deployments based on allocations
func (sp *StackelbergPlugin) handleReplicaScaling(ctx context.Context, tenant string, allocation *TenantAllocation, namespace string) {
	// Use a longer timeout and create a fresh context to avoid cancellation issues
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	// Add retry logic with exponential backoff
	maxRetries := 5
	baseDelay := 2 * time.Second
	
	for attempt := 0; attempt < maxRetries; attempt++ {
		if attempt > 0 {
			delay := time.Duration(1<<uint(attempt-1)) * baseDelay // Exponential backoff
			klog.V(3).Infof("Retrying deployment operation for tenant %s (attempt %d/%d) after %v", tenant, attempt+1, maxRetries, delay)
			
			select {
			case <-time.After(delay):
			case <-ctx.Done():
				klog.Errorf("Context canceled while waiting to retry for tenant %s", tenant)
				return
			}
		}
		
		if err := sp.tryHandleReplicaScaling(ctx, tenant, allocation, namespace); err != nil {
			klog.Errorf("Attempt %d failed for tenant %s: %v", attempt+1, tenant, err)
			if attempt == maxRetries-1 {
				klog.Errorf("All attempts failed for tenant %s deployment management", tenant)
			}
			continue
		}
		
		// Success
		klog.V(2).Infof("Successfully handled replica scaling for tenant %s", tenant)
		return
	}
}

// tryHandleReplicaScaling attempts to handle replica scaling once
func (sp *StackelbergPlugin) tryHandleReplicaScaling(ctx context.Context, tenant string, allocation *TenantAllocation, namespace string) error {
	deploymentName := fmt.Sprintf("%s-deployment", tenant)
	
	// Check if deployment exists first
	deployment, err := sp.handle.ClientSet().AppsV1().Deployments(namespace).Get(ctx, deploymentName, metav1.GetOptions{})
	if err != nil {
		// Check if it's a "not found" error
		if !errors.IsNotFound(err) {
			return fmt.Errorf("failed to get deployment %s: %v", deploymentName, err)
		}
		
		// Deployment doesn't exist, create it
		klog.V(2).Infof("Creating deployment %s for tenant %s with %d replicas", deploymentName, tenant, allocation.Replicas)
		return sp.createDeployment(ctx, tenant, allocation, namespace)
	}

	// Deployment exists, update replicas if needed
	currentReplicas := int32(0)
	if deployment.Spec.Replicas != nil {
		currentReplicas = *deployment.Spec.Replicas
	}

	targetReplicas := int32(allocation.Replicas)
	if currentReplicas != targetReplicas {
		klog.V(2).Infof("Scaling deployment %s from %d to %d replicas", deploymentName, currentReplicas, targetReplicas)
		deployment.Spec.Replicas = &targetReplicas
		
		// Update resource requirements in the deployment template
		sp.updateDeploymentResources(deployment, allocation)
		
		_, err = sp.handle.ClientSet().AppsV1().Deployments(namespace).Update(ctx, deployment, metav1.UpdateOptions{})
		if err != nil {
			return fmt.Errorf("failed to update deployment %s: %v", deploymentName, err)
		}
	} else {
		// Even if replicas are the same, update resources if they've changed
		if sp.resourcesNeedUpdate(deployment, allocation) {
			klog.V(2).Infof("Updating resources for deployment %s", deploymentName)
			sp.updateDeploymentResources(deployment, allocation)
			
			_, err = sp.handle.ClientSet().AppsV1().Deployments(namespace).Update(ctx, deployment, metav1.UpdateOptions{})
			if err != nil {
				return fmt.Errorf("failed to update deployment resources %s: %v", deploymentName, err)
			}
		}
	}
	
	klog.V(4).Infof("Deployment %s is up to date with %d replicas", deploymentName, targetReplicas)
	return nil
}

// resourcesNeedUpdate checks if deployment resources need to be updated
func (sp *StackelbergPlugin) resourcesNeedUpdate(deployment *appsv1.Deployment, allocation *TenantAllocation) bool {
	if len(deployment.Spec.Template.Spec.Containers) == 0 {
		return true
	}
	
	container := deployment.Spec.Template.Spec.Containers[0]
	expectedCPU := resource.NewMilliQuantity(int64(allocation.CPUPerReplica*1000), resource.DecimalSI)
	expectedMemory := resource.NewQuantity(int64(allocation.MemoryPerReplica*1024*1024*1024), resource.BinarySI)
	
	currentCPU := container.Resources.Requests[v1.ResourceCPU]
	currentMemory := container.Resources.Requests[v1.ResourceMemory]
	
	return !currentCPU.Equal(*expectedCPU) || !currentMemory.Equal(*expectedMemory)
}

// createDeployment creates a new deployment for the tenant with improved error handling
func (sp *StackelbergPlugin) createDeployment(ctx context.Context, tenant string, allocation *TenantAllocation, namespace string) error {
	deploymentName := fmt.Sprintf("%s-deployment", tenant)
	appName := fmt.Sprintf("%s-app", tenant)
	replicas := int32(allocation.Replicas)

	cpuQuantity := resource.NewMilliQuantity(int64(allocation.CPUPerReplica*1000), resource.DecimalSI)
	memoryQuantity := resource.NewQuantity(int64(allocation.MemoryPerReplica*1024*1024*1024), resource.BinarySI)

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      deploymentName,
			Namespace: namespace,
			Labels: map[string]string{
				TenantLabel: tenant,
				"app":       appName,
				"managed-by": "stackelberg-scheduler",
			},
			Annotations: map[string]string{
				AnnotationCPUAllocated:    strconv.FormatFloat(allocation.CPUPerReplica, 'f', 2, 64),
				AnnotationMemoryAllocated: strconv.FormatFloat(allocation.MemoryPerReplica, 'f', 2, 64),
				AnnotationReplicas:        strconv.Itoa(allocation.Replicas),
			},
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: map[string]string{
					TenantLabel: tenant,
					"app":       appName,
				},
			},
			Template: v1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: map[string]string{
						TenantLabel: tenant,
						"app":       appName,
					},
					Annotations: map[string]string{
						AnnotationCPUAllocated:      strconv.FormatFloat(allocation.CPUPerReplica, 'f', 2, 64),
						AnnotationMemoryAllocated:   strconv.FormatFloat(allocation.MemoryPerReplica, 'f', 2, 64),
						AnnotationReplicas:          strconv.Itoa(allocation.Replicas),
						AnnotationAllocationApplied: "true",
					},
				},
				Spec: v1.PodSpec{
					SchedulerName: Name,
					Containers: []v1.Container{
						{
							Name:  fmt.Sprintf("%s-container", tenant),
							Image: sp.getImageForTenant(tenant),
							Resources: v1.ResourceRequirements{
								Requests: v1.ResourceList{
									v1.ResourceCPU:    *cpuQuantity,
									v1.ResourceMemory: *memoryQuantity,
								},
								Limits: v1.ResourceList{
									v1.ResourceCPU:    *cpuQuantity,
									v1.ResourceMemory: *memoryQuantity,
								},
							},
							Ports: sp.getPortsForTenant(tenant),
						},
					},
				},
			},
		},
	}

	// Create the deployment with retry logic for rate limiting
	created, err := sp.handle.ClientSet().AppsV1().Deployments(namespace).Create(ctx, deployment, metav1.CreateOptions{})
	if err != nil {
		// If deployment already exists, that's fine - another instance might have created it
		if errors.IsAlreadyExists(err) {
			klog.V(2).Infof("Deployment %s already exists, skipping creation", deploymentName)
			return nil
		}
		return fmt.Errorf("failed to create deployment %s: %v", deploymentName, err)
	}
	
	klog.V(2).Infof("Successfully created deployment %s with %d replicas", created.Name, replicas)
	return nil
}

// updateDeploymentResources updates the resource requirements in a deployment template
func (sp *StackelbergPlugin) updateDeploymentResources(deployment *appsv1.Deployment, allocation *TenantAllocation) {
	cpuQuantity := resource.NewMilliQuantity(int64(allocation.CPUPerReplica*1000), resource.DecimalSI)
	memoryQuantity := resource.NewQuantity(int64(allocation.MemoryPerReplica*1024*1024*1024), resource.BinarySI)

	for i := range deployment.Spec.Template.Spec.Containers {
		container := &deployment.Spec.Template.Spec.Containers[i]
		if container.Resources.Requests == nil {
			container.Resources.Requests = make(v1.ResourceList)
		}
		if container.Resources.Limits == nil {
			container.Resources.Limits = make(v1.ResourceList)
		}

		container.Resources.Requests[v1.ResourceCPU] = *cpuQuantity
		container.Resources.Requests[v1.ResourceMemory] = *memoryQuantity
		container.Resources.Limits[v1.ResourceCPU] = *cpuQuantity
		container.Resources.Limits[v1.ResourceMemory] = *memoryQuantity
	}

	// Update annotations
	if deployment.Spec.Template.Annotations == nil {
		deployment.Spec.Template.Annotations = make(map[string]string)
	}
	deployment.Spec.Template.Annotations[AnnotationCPUAllocated] = strconv.FormatFloat(allocation.CPUPerReplica, 'f', 2, 64)
	deployment.Spec.Template.Annotations[AnnotationMemoryAllocated] = strconv.FormatFloat(allocation.MemoryPerReplica, 'f', 2, 64)
	deployment.Spec.Template.Annotations[AnnotationReplicas] = strconv.Itoa(allocation.Replicas)
	deployment.Spec.Template.Annotations[AnnotationAllocationApplied] = "true"
}

// getImageForTenant returns the appropriate container image for each tenant
func (sp *StackelbergPlugin) getImageForTenant(tenant string) string {
	switch tenant {
	case WebAppTenant:
		return "nginx:alpine" // Web app image
	case DataProcessingTenant:
		return "k8s.gcr.io/pause:3.2" // Data processing image
	case MLTrainingTenant:
		return "k8s.gcr.io/pause:3.2" // ML training image
	default:
		return "k8s.gcr.io/pause:3.2"
	}
}

// getPortsForTenant returns the appropriate ports for each tenant
func (sp *StackelbergPlugin) getPortsForTenant(tenant string) []v1.ContainerPort {
	switch tenant {
	case WebAppTenant:
		return []v1.ContainerPort{
			{
				ContainerPort: 80,
				Protocol:      v1.ProtocolTCP,
			},
		}
	case DataProcessingTenant:
		return []v1.ContainerPort{
			{
				ContainerPort: 8080,
				Protocol:      v1.ProtocolTCP,
			},
		}
	case MLTrainingTenant:
		return []v1.ContainerPort{
			{
				ContainerPort: 9000,
				Protocol:      v1.ProtocolTCP,
			},
		}
	default:
		return []v1.ContainerPort{}
	}
}

func (sp *StackelbergPlugin) calculateClusterResources(nodes []v1.Node) (float64, float64) {
	var totalCPU, totalMemory float64

	for _, node := range nodes {
		if node.Spec.Unschedulable {
			continue
		}

		cpuQuantity := node.Status.Allocatable[v1.ResourceCPU]
		memoryQuantity := node.Status.Allocatable[v1.ResourceMemory]

		cpu := float64(cpuQuantity.MilliValue()) / 1000.0
		memory := float64(memoryQuantity.Value()) / (1024 * 1024 * 1024)

		totalCPU += cpu
		totalMemory += memory
	}

	return totalCPU, totalMemory
}

func (sp *StackelbergPlugin) getTenantPodCounts(ctx context.Context) (map[string]int, error) {
	pods, err := sp.handle.ClientSet().CoreV1().Pods("").List(ctx, metav1.ListOptions{
		FieldSelector: "status.phase=Running",
	})
	if err != nil {
		return nil, err
	}

	counts := map[string]int{
		WebAppTenant:         0,
		DataProcessingTenant: 0,
		MLTrainingTenant:     0,
	}

	for _, pod := range pods.Items {
		if tenant, exists := pod.Labels[TenantLabel]; exists && isValidTenant(tenant) {
			counts[tenant]++
		}
	}

	return counts, nil
}

func (sp *StackelbergPlugin) prepareAPIRequest(totalCPU, totalMemory float64, podCounts map[string]int) *APIRequest {
	params, err := loadParamsFromConfig("/etc/stackelberg/params.json")
	if err != nil {
		panic(err)
	}

	return &APIRequest{
		TotalCPU:    totalCPU,
		TotalMemory: totalMemory,
		Params:      params,
	}
}


func (sp *StackelbergPlugin) callStackelbergAPI(req *APIRequest) (*APIResponse, error) {
	jsonData, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %v", err)
	}

	resp, err := sp.client.Post(sp.apiURL, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, fmt.Errorf("HTTP request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("API returned status %d: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %v", err)
	}

	var apiResp APIResponse
	err = json.Unmarshal(body, &apiResp)
	if err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %v", err)
	}

	klog.V(4).Infof("Stackelberg API response: %+v", apiResp)
	return &apiResp, nil
}

func (sp *StackelbergPlugin) findTenantAllocation(allocations []TenantAllocation, tenant string) *TenantAllocation {
	tenantMap := map[string]string{
		WebAppTenant:         "Web-App",
		DataProcessingTenant: "Data-Processing",
		MLTrainingTenant:     "ML-Training",
	}

	expectedTenant := tenantMap[tenant]
	for i := range allocations {
		if allocations[i].Tenant == expectedTenant {
			return &allocations[i]
		}
	}
	return nil
}

func (sp *StackelbergPlugin) updatePodResources(pod *v1.Pod, allocation *TenantAllocation) error {
	cpuQuantity := resource.NewMilliQuantity(int64(allocation.CPUPerReplica*1000), resource.DecimalSI)
	memoryQuantity := resource.NewQuantity(int64(allocation.MemoryPerReplica*1024*1024*1024), resource.BinarySI)

	for i := range pod.Spec.Containers {
		if pod.Spec.Containers[i].Resources.Requests == nil {
			pod.Spec.Containers[i].Resources.Requests = make(v1.ResourceList)
		}
		if pod.Spec.Containers[i].Resources.Limits == nil {
			pod.Spec.Containers[i].Resources.Limits = make(v1.ResourceList)
		}

		pod.Spec.Containers[i].Resources.Requests[v1.ResourceCPU] = *cpuQuantity
		pod.Spec.Containers[i].Resources.Requests[v1.ResourceMemory] = *memoryQuantity
		pod.Spec.Containers[i].Resources.Limits[v1.ResourceCPU] = *cpuQuantity
		pod.Spec.Containers[i].Resources.Limits[v1.ResourceMemory] = *memoryQuantity
	}

	if pod.Annotations == nil {
		pod.Annotations = make(map[string]string)
	}
	pod.Annotations[AnnotationCPUAllocated] = strconv.FormatFloat(allocation.CPUPerReplica, 'f', 2, 64)
	pod.Annotations[AnnotationMemoryAllocated] = strconv.FormatFloat(allocation.MemoryPerReplica, 'f', 2, 64)
	pod.Annotations[AnnotationReplicas] = strconv.Itoa(allocation.Replicas)
	pod.Annotations[AnnotationAllocationApplied] = "true"

	return nil
}

func isValidTenant(tenant string) bool {
	switch tenant {
	case WebAppTenant, DataProcessingTenant, MLTrainingTenant:
		return true
	default:
		return false
	}
}