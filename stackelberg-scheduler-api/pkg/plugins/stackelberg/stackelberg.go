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

	v1 "k8s.io/api/core/v1"
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
	out.TypeMeta = in.TypeMeta // Simple assignment for TypeMeta
	return out
}

func New(obj runtime.Object, h framework.Handle) (framework.Plugin, error) {
	// Handle the args parsing gracefully - use defaults if parsing fails
	apiURL := "http://stackelberg-api-service.kube-system:5000/stackelberg/allocate"
	timeout := 30
	
	// Try to parse args if provided
	if obj != nil {
		klog.V(4).Infof("Received args object of type: %T", obj)
		
		// For now, use the hardcoded endpoint since args parsing is failing
		// This is a temporary fix - the config file args aren't being parsed correctly
		if unknown, ok := obj.(*runtime.Unknown); ok {
			klog.V(4).Infof("Got runtime.Unknown with raw data: %s", string(unknown.Raw))
			// TODO: Parse the raw JSON manually if needed
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

	klog.V(2).Infof("Updated pod %s/%s resources: CPU=%v, Memory=%v", 
		pod.Namespace, pod.Name, 
		allocation.CPUPerReplica, allocation.MemoryPerReplica)

	return nil, framework.NewStatus(framework.Success, "")
}

func (sp *StackelbergPlugin) PreFilterExtensions() framework.PreFilterExtensions {
	return nil
}

func (sp *StackelbergPlugin) calculateClusterResources(nodes []v1.Node) (float64, float64) {
	var totalCPU, totalMemory float64

	for _, node := range nodes {
		if node.Spec.Unschedulable {
			continue
		}

		cpuQuantity := node.Status.Allocatable[v1.ResourceCPU]
		memoryQuantity := node.Status.Allocatable[v1.ResourceMemory]

		cpu := float64(cpuQuantity.MilliValue()) / 1000.0 // Convert millicores to cores
		memory := float64(memoryQuantity.Value()) / (1024 * 1024 * 1024) // Convert bytes to GB

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
	params := map[string]float64{
		"web_app_max_response_time":           52.5,
		"web_app_budget":                      800.0,
		"web_app_min_cpu":                     0.2,
		"web_app_min_memory":                  1.0,
		"web_app_desired_replicas":            float64(podCounts[WebAppTenant] + 1),
		"web_app_min_replicas":                1.0,
		
		"data_processing_min_throughput":      1000.0,
		"data_processing_budget":              1200.0,
		"data_processing_min_cpu":             0.5,
		"data_processing_min_memory":          1.0,
		"data_processing_desired_replicas":    float64(podCounts[DataProcessingTenant] + 1),
		"data_processing_min_replicas":        1.0,
		
		"ml_training_max_training_time":       8.0,
		"ml_training_budget":                  1500.0,
		"ml_training_min_cpu":                 0.4,
		"ml_training_min_memory":              1.0,
		"ml_training_desired_replicas":        float64(podCounts[MLTrainingTenant] + 1),
		"ml_training_min_replicas":            1.0,
		
		"alpha1":                              0.3,
		"alpha2":                              0.2,
		"alpha3":                              0.5,
		
		"cpu_norm":                            2.0,
		"memory_norm":                         4.0,
		"base_exponent":                       0.7,
		"rt_const1":                           50.0,
		"rt_const2":                           500.0,
		"rt_exponent":                         0.3,
		"latency_thresh":                      52.5,
		"latency_penalty":                     100.0,
		
		"tenant_b_base_coeff":                 120.0,
		"tenant_b_memory_exp1":                0.6,
		"tenant_b_base_exp":                   0.8,
		"tenant_b_throughput_coeff":           15.0,
		"tenant_b_throughput_cpu_exp":         0.8,
		"tenant_b_throughput_mem_exp":         0.4,
		"tenant_b_queue_penalty_thresh":       1000.0,
		"tenant_b_queue_penalty_coeff":        2.0,
		
		"tenant_c_base_coeff":                 120.0,
		"tenant_c_memory_exp1":                0.5,
		"tenant_c_log_const":                  1.0,
		"tenant_c_training_cpu_exp":           0.7,
		"tenant_c_training_mem_exp":           0.3,
		"tenant_c_time_penalty_thresh":        8.0,
		"tenant_c_time_penalty_coeff":         40.0,
		
		"initial_p_cpu":                       5.0,
		"initial_p_memory":                    2.0,
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
	pod.Annotations["stackelberg.scheduler/cpu-allocated"] = strconv.FormatFloat(allocation.CPUPerReplica, 'f', 2, 64)
	pod.Annotations["stackelberg.scheduler/memory-allocated"] = strconv.FormatFloat(allocation.MemoryPerReplica, 'f', 2, 64)
	pod.Annotations["stackelberg.scheduler/replicas"] = strconv.Itoa(allocation.Replicas)

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