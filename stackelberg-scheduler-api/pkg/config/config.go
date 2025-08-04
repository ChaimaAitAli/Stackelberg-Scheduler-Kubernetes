package config

import (
	"os"
	"gopkg.in/yaml.v3"
)

type Config struct {
	WebApp struct {
		MaxResponseTime float64 `yaml:"max_response_time"`
		Budget          float64 `yaml:"budget"`
		MinCPU          float64 `yaml:"min_cpu"`
		MinMemory       float64 `yaml:"min_memory"`
		DesiredReplicas float64 `yaml:"desired_replicas"`
		MinReplicas     float64 `yaml:"min_replicas"`
	} `yaml:"web_app"`

	DataProcessing struct {
		MinThroughput   float64 `yaml:"min_throughput"`
		Budget          float64 `yaml:"budget"`
		MinCPU          float64 `yaml:"min_cpu"`
		MinMemory       float64 `yaml:"min_memory"`
		DesiredReplicas float64 `yaml:"desired_replicas"`
		MinReplicas     float64 `yaml:"min_replicas"`
	} `yaml:"data_processing"`

	MLTraining struct {
		MaxTrainingTime float64 `yaml:"max_training_time"`
		Budget          float64 `yaml:"budget"`
		MinCPU          float64 `yaml:"min_cpu"`
		MinMemory       float64 `yaml:"min_memory"`
		DesiredReplicas float64 `yaml:"desired_replicas"`
		MinReplicas     float64 `yaml:"min_replicas"`
	} `yaml:"ml_training"`

	Weights struct {
		Alpha1 float64 `yaml:"alpha1"`
		Alpha2 float64 `yaml:"alpha2"`
		Alpha3 float64 `yaml:"alpha3"`
	} `yaml:"weights"`

	Normalization struct {
		CPUNorm    float64 `yaml:"cpu_norm"`
		MemoryNorm float64 `yaml:"memory_norm"`
	} `yaml:"normalization"`

	Latency struct {
		BaseExponent    float64 `yaml:"base_exponent"`
		RTConst1        float64 `yaml:"rt_const1"`
		RTConst2        float64 `yaml:"rt_const2"`
		RTExponent      float64 `yaml:"rt_exponent"`
		LatencyThresh   float64 `yaml:"latency_thresh"`
		LatencyPenalty  float64 `yaml:"latency_penalty"`
	} `yaml:"latency"`

	TenantB struct {
		BaseCoeff           float64 `yaml:"base_coeff"`
		MemoryExp1          float64 `yaml:"memory_exp1"`
		BaseExp             float64 `yaml:"base_exp"`
		ThroughputCoeff     float64 `yaml:"throughput_coeff"`
		ThroughputCPUExp    float64 `yaml:"throughput_cpu_exp"`
		ThroughputMemExp    float64 `yaml:"throughput_mem_exp"`
		QueuePenaltyThresh  float64 `yaml:"queue_penalty_thresh"`
		QueuePenaltyCoeff   float64 `yaml:"queue_penalty_coeff"`
	} `yaml:"tenant_b"`

	TenantC struct {
		BaseCoeff         float64 `yaml:"base_coeff"`
		MemoryExp1        float64 `yaml:"memory_exp1"`
		LogConst          float64 `yaml:"log_const"`
		TrainingCPUExp    float64 `yaml:"training_cpu_exp"`
		TrainingMemExp    float64 `yaml:"training_mem_exp"`
		TimePenaltyThresh float64 `yaml:"time_penalty_thresh"`
		TimePenaltyCoeff  float64 `yaml:"time_penalty_coeff"`
	} `yaml:"tenant_c"`

	InitialPrices struct {
		CPU    float64 `yaml:"cpu"`
		Memory float64 `yaml:"memory"`
	} `yaml:"initial_prices"`
}

func LoadConfig(path string) (*Config, error) {
	cfg := &Config{}
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if err := yaml.Unmarshal(content, cfg); err != nil {
		return nil, err
	}
	return cfg, nil
}
