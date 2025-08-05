#!/usr/bin/env python3
"""
Enhanced Kubernetes Scheduler Comparison Framework
Compares Stackelberg Scheduler vs Regular Kubernetes Scheduler with SLO Violations
"""

import subprocess
import time
import json
import yaml
import requests
import matplotlib.pyplot as plt
import pandas as pd
from typing import Dict, List, Tuple
import logging
from datetime import datetime
import numpy as np

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class EnhancedSchedulerComparison:
    def __init__(self, namespace: str = "default", config_file: str = "deploy/stackelberg-config.yaml"):
        self.namespace = namespace
        self.config_file = config_file
        self.config_params = self.load_config_parameters()
        self.metrics = {
            'stackelberg': {},
            'regular': {}
        }
        
    def load_config_parameters(self) -> Dict:
        """Load parameters from stackelberg-config.yaml ConfigMap"""
        try:
            with open(self.config_file, 'r') as f:
                config_yaml = yaml.safe_load(f)
            
            # Extract the config data from the ConfigMap
            config_data = yaml.safe_load(config_yaml['data']['config.yaml'])
            
            # Convert to the format expected by the Stackelberg scheduler
            params = {}
            
            # Web App parameters
            web_app = config_data['web_app']
            params['web_app_max_response_time'] = web_app['max_response_time']
            params['web_app_budget'] = web_app['budget']
            params['web_app_min_cpu'] = web_app['min_cpu']
            params['web_app_min_memory'] = web_app['min_memory']
            params['web_app_desired_replicas'] = web_app['desired_replicas']
            params['web_app_min_replicas'] = web_app['min_replicas']
            
            # Data Processing parameters
            data_proc = config_data['data_processing']
            params['data_processing_min_throughput'] = data_proc['min_throughput']
            params['data_processing_budget'] = data_proc['budget']
            params['data_processing_min_cpu'] = data_proc['min_cpu']
            params['data_processing_min_memory'] = data_proc['min_memory']
            params['data_processing_desired_replicas'] = data_proc['desired_replicas']
            params['data_processing_min_replicas'] = data_proc['min_replicas']
            
            # ML Training parameters
            ml_train = config_data['ml_training']
            params['ml_training_max_training_time'] = ml_train['max_training_time']
            params['ml_training_budget'] = ml_train['budget']
            params['ml_training_min_cpu'] = ml_train['min_cpu']
            params['ml_training_min_memory'] = ml_train['min_memory']
            params['ml_training_desired_replicas'] = ml_train['desired_replicas']
            params['ml_training_min_replicas'] = ml_train['min_replicas']
            
            # Weights
            weights = config_data['weights']
            params['alpha1'] = weights['alpha1']
            params['alpha2'] = weights['alpha2']
            params['alpha3'] = weights['alpha3']
            
            # Normalization
            norm = config_data['normalization']
            params['cpu_norm'] = norm['cpu_norm']
            params['memory_norm'] = norm['memory_norm']
            
            # Latency parameters
            latency = config_data['latency']
            params['base_exponent'] = latency['base_exponent']
            params['rt_const1'] = latency['rt_const1']
            params['rt_const2'] = latency['rt_const2']
            params['rt_exponent'] = latency['rt_exponent']
            params['latency_thresh'] = latency['latency_thresh']
            params['latency_penalty'] = latency['latency_penalty']
            
            # Tenant B parameters
            tenant_b = config_data['tenant_b']
            params['tenant_b_base_coeff'] = tenant_b['base_coeff']
            params['tenant_b_memory_exp1'] = tenant_b['memory_exp1']
            params['tenant_b_base_exp'] = tenant_b['base_exp']
            params['tenant_b_throughput_coeff'] = tenant_b['throughput_coeff']
            params['tenant_b_throughput_cpu_exp'] = tenant_b['throughput_cpu_exp']
            params['tenant_b_throughput_mem_exp'] = tenant_b['throughput_mem_exp']
            params['tenant_b_queue_penalty_thresh'] = tenant_b['queue_penalty_thresh']
            params['tenant_b_queue_penalty_coeff'] = tenant_b['queue_penalty_coeff']
            
            # Tenant C parameters
            tenant_c = config_data['tenant_c']
            params['tenant_c_base_coeff'] = tenant_c['base_coeff']
            params['tenant_c_memory_exp1'] = tenant_c['memory_exp1']
            params['tenant_c_log_const'] = tenant_c['log_const']
            params['tenant_c_training_cpu_exp'] = tenant_c['training_cpu_exp']
            params['tenant_c_training_mem_exp'] = tenant_c['training_mem_exp']
            params['tenant_c_time_penalty_thresh'] = tenant_c['time_penalty_thresh']
            params['tenant_c_time_penalty_coeff'] = tenant_c['time_penalty_coeff']
            
            # Initial prices
            initial_prices = config_data['initial_prices']
            params['initial_p_cpu'] = initial_prices['cpu']
            params['initial_p_memory'] = initial_prices['memory']
            
            logger.info(f"Loaded {len(params)} parameters from config file")
            return params
            
        except Exception as e:
            logger.error(f"Failed to load config parameters: {e}")
            return {}
    
    def get_cluster_resources(self) -> Tuple[float, float]:
        """Get total cluster CPU and Memory resources"""
        try:
            result = subprocess.run(['kubectl', 'get', 'nodes', '-o', 'json'], 
                                  capture_output=True, text=True, check=True)
            nodes = json.loads(result.stdout)
            
            total_cpu = 0
            total_memory = 0
            
            for node in nodes['items']:
                if not node['spec'].get('unschedulable', False):
                    allocatable = node['status']['allocatable']
                    cpu_str = allocatable['cpu']
                    memory_str = allocatable['memory']
                    
                    # Convert CPU (cores to millicores)
                    if cpu_str.endswith('m'):
                        cpu = float(cpu_str[:-1]) / 1000
                    else:
                        cpu = float(cpu_str)
                    
                    # Convert Memory (bytes to GB)
                    if memory_str.endswith('Ki'):
                        memory = float(memory_str[:-2]) / (1024 * 1024)
                    elif memory_str.endswith('Mi'):
                        memory = float(memory_str[:-2]) / 1024
                    elif memory_str.endswith('Gi'):
                        memory = float(memory_str[:-2])
                    else:
                        memory = float(memory_str) / (1024**3)
                    
                    total_cpu += cpu
                    total_memory += memory
            
            logger.info(f"Cluster resources: CPU={total_cpu:.2f} cores, Memory={total_memory:.2f} GB")
            return total_cpu, total_memory
            
        except Exception as e:
            logger.error(f"Failed to get cluster resources: {e}")
            # Fallback for typical development environment
            return 4.0, 8.0  # Assume 4 cores, 8GB RAM
    
    def calculate_slo_violations(self, scheduler_name: str, resource_allocations: Dict) -> Dict:
        """Calculate SLO violations for tenants based on their resource allocations"""
        slo_violations = {
            'web-app': {'violated': False, 'severity': 0, 'metric_value': 0, 'threshold': 0},
            'data-processing': {'violated': False, 'severity': 0, 'metric_value': 0, 'threshold': 0},
            'ml-training': {'violated': False, 'severity': 0, 'metric_value': 0, 'threshold': 0}
        }
        
        try:
            # Web App - Response Time SLO
            if 'web-app' in resource_allocations:
                alloc = resource_allocations['web-app']
                cpu_per_replica = alloc['cpu_per_replica']
                memory_per_replica = alloc['memory_per_replica']
                
                # Use config parameters for calculation
                rt_const1 = self.config_params.get('rt_const1', 80.0)
                rt_const2 = self.config_params.get('rt_const2', 300.0)
                rt_exponent = self.config_params.get('rt_exponent', 0.3)
                latency_thresh = self.config_params.get('latency_thresh', 100.0)
                
                response_time = rt_const1 + rt_const2 / (cpu_per_replica * memory_per_replica ** rt_exponent)
                
                slo_violations['web-app']['metric_value'] = response_time
                slo_violations['web-app']['threshold'] = latency_thresh
                slo_violations['web-app']['violated'] = response_time > latency_thresh
                slo_violations['web-app']['severity'] = max(0, (response_time - latency_thresh) / latency_thresh) if response_time > latency_thresh else 0
            
            # Data Processing - Throughput SLO
            if 'data-processing' in resource_allocations:
                alloc = resource_allocations['data-processing']
                cpu_per_replica = alloc['cpu_per_replica']
                memory_per_replica = alloc['memory_per_replica']
                replicas = alloc['replicas']
                
                throughput_coeff = self.config_params.get('tenant_b_throughput_coeff', 10.0)
                throughput_cpu_exp = self.config_params.get('tenant_b_throughput_cpu_exp', 0.8)
                throughput_mem_exp = self.config_params.get('tenant_b_throughput_mem_exp', 0.4)
                min_throughput = self.config_params.get('data_processing_min_throughput', 500.0)
                
                actual_throughput = throughput_coeff * cpu_per_replica ** throughput_cpu_exp * memory_per_replica ** throughput_mem_exp * replicas
                
                slo_violations['data-processing']['metric_value'] = actual_throughput
                slo_violations['data-processing']['threshold'] = min_throughput
                slo_violations['data-processing']['violated'] = actual_throughput < min_throughput
                slo_violations['data-processing']['severity'] = max(0, (min_throughput - actual_throughput) / min_throughput) if actual_throughput < min_throughput else 0
            
            # ML Training - Training Time SLO
            if 'ml-training' in resource_allocations:
                alloc = resource_allocations['ml-training']
                cpu_per_replica = alloc['cpu_per_replica']
                memory_per_replica = alloc['memory_per_replica']
                
                training_cpu_exp = self.config_params.get('tenant_c_training_cpu_exp', 0.7)
                training_mem_exp = self.config_params.get('tenant_c_training_mem_exp', 0.3)
                max_training_time = self.config_params.get('ml_training_max_training_time', 15.0)
                
                training_time = 20 / (cpu_per_replica ** training_cpu_exp * memory_per_replica ** training_mem_exp)
                
                slo_violations['ml-training']['metric_value'] = training_time
                slo_violations['ml-training']['threshold'] = max_training_time
                slo_violations['ml-training']['violated'] = training_time > max_training_time
                slo_violations['ml-training']['severity'] = max(0, (training_time - max_training_time) / max_training_time) if training_time > max_training_time else 0
                
        except Exception as e:
            logger.error(f"Error calculating SLO violations: {e}")
        
        return slo_violations
    
    def get_resource_allocations_from_pods(self, scheduler_name: str) -> Dict:
        """Extract resource allocations from running pods"""
        try:
            result = subprocess.run(['kubectl', 'get', 'pods', '-n', self.namespace,
                                   '-o', 'json'], 
                                  capture_output=True, text=True, check=True)
            pods = json.loads(result.stdout)
            
            tenant_allocations = {}
            
            for pod in pods['items']:
                # Filter pods based on scheduler
                if scheduler_name == "default-scheduler" and pod['spec'].get('schedulerName') == 'stackelberg-scheduler':
                    continue
                if scheduler_name == "stackelberg-scheduler" and pod['spec'].get('schedulerName') != 'stackelberg-scheduler':
                    continue
                
                if pod['status']['phase'] != 'Running':
                    continue
                
                tenant = pod['metadata'].get('labels', {}).get('tenant')
                if not tenant:
                    continue
                
                if tenant not in tenant_allocations:
                    tenant_allocations[tenant] = {
                        'total_cpu': 0,
                        'total_memory': 0,
                        'replicas': 0,
                        'cpu_per_replica': 0,
                        'memory_per_replica': 0
                    }
                
                # Sum up resources from containers
                pod_cpu = pod_memory = 0
                for container in pod['spec'].get('containers', []):
                    requests = container.get('resources', {}).get('requests', {})
                    
                    if 'cpu' in requests:
                        cpu_val = requests['cpu']
                        if cpu_val.endswith('m'):
                            pod_cpu += float(cpu_val[:-1]) / 1000
                        else:
                            pod_cpu += float(cpu_val)
                    
                    if 'memory' in requests:
                        mem_val = requests['memory']
                        if mem_val.endswith('Mi'):
                            pod_memory += float(mem_val[:-2]) / 1024
                        elif mem_val.endswith('Gi'):
                            pod_memory += float(mem_val[:-2])
                
                tenant_allocations[tenant]['total_cpu'] += pod_cpu
                tenant_allocations[tenant]['total_memory'] += pod_memory
                tenant_allocations[tenant]['replicas'] += 1
            
            # Calculate per-replica averages
            for tenant, alloc in tenant_allocations.items():
                if alloc['replicas'] > 0:
                    alloc['cpu_per_replica'] = alloc['total_cpu'] / alloc['replicas']
                    alloc['memory_per_replica'] = alloc['total_memory'] / alloc['replicas']
            
            return tenant_allocations
            
        except Exception as e:
            logger.error(f"Failed to get resource allocations: {e}")
            return {}
    
    def cleanup_deployments(self):
        """Clean up all test deployments"""
        logger.info("Cleaning up existing deployments...")
        deployments = [
            'web-app-deployment', 'data-processing-deployment', 'ml-training-deployment',
            'regular-web-app', 'regular-data-processing', 'regular-ml-training'
        ]
        
        for deployment in deployments:
            try:
                subprocess.run(['kubectl', 'delete', 'deployment', deployment, '-n', self.namespace], 
                             capture_output=True, check=False)
            except:
                pass
        
        # Wait for cleanup
        time.sleep(30)
    
    def apply_config(self, config_file: str):
        """Apply Kubernetes configuration"""
        try:
            result = subprocess.run(['kubectl', 'apply', '-f', config_file], 
                                  capture_output=True, text=True, check=True)
            logger.info(f"Applied config: {config_file}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to apply {config_file}: {e.stderr}")
            return False
    
    def wait_for_pods_ready(self, scheduler_name: str, timeout: int = 300):
        """Wait for all pods to be ready"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                if scheduler_name == "stackelberg-scheduler":
                    result = subprocess.run(['kubectl', 'get', 'pods', '-n', self.namespace,
                                           '-l', 'tenant', '-o', 'json'], 
                                          capture_output=True, text=True, check=True)
                else:
                    result = subprocess.run(['kubectl', 'get', 'pods', '-n', self.namespace,
                                           '-o', 'json'], 
                                          capture_output=True, text=True, check=True)
                
                pods = json.loads(result.stdout)
                total_pods = 0
                ready_pods = 0
                
                for pod in pods['items']:
                    if scheduler_name == "default-scheduler":
                        if pod['spec'].get('schedulerName') == 'stackelberg-scheduler':
                            continue
                    elif scheduler_name == "stackelberg-scheduler":
                        if pod['spec'].get('schedulerName') != 'stackelberg-scheduler':
                            continue
                    
                    total_pods += 1
                    if pod['status']['phase'] == 'Running':
                        ready_pods += 1
                
                logger.info(f"Pods ready: {ready_pods}/{total_pods} for {scheduler_name}")
                
                if ready_pods >= total_pods and total_pods > 0:
                    return True
                    
            except Exception as e:
                logger.warning(f"Error checking pod status: {e}")
            
            time.sleep(10)
        
        return False
    
    def collect_enhanced_metrics(self, scheduler_name: str) -> Dict:
        """Collect enhanced performance metrics including SLO violations"""
        try:
            result = subprocess.run(['kubectl', 'get', 'pods', '-n', self.namespace,
                                   '-o', 'json'], 
                                  capture_output=True, text=True, check=True)
            pods = json.loads(result.stdout)
            
            metrics = {
                'total_pods': 0,
                'running_pods': 0,
                'failed_pods': 0,
                'resource_usage': {'cpu': 0, 'memory': 0},
                'tenant_metrics': {},
                'scheduling_time': 0,
                'resource_efficiency': 0,
                'slo_violations': {},
                'total_slo_violations': 0,
                'avg_slo_severity': 0
            }
            
            tenant_pods = {'web-app': [], 'data-processing': [], 'ml-training': []}
            
            for pod in pods['items']:
                if scheduler_name == "default-scheduler" and pod['spec'].get('schedulerName') == 'stackelberg-scheduler':
                    continue
                if scheduler_name == "stackelberg-scheduler" and pod['spec'].get('schedulerName') != 'stackelberg-scheduler':
                    continue
                
                metrics['total_pods'] += 1
                
                if pod['status']['phase'] == 'Running':
                    metrics['running_pods'] += 1
                elif pod['status']['phase'] == 'Failed':
                    metrics['failed_pods'] += 1
                
                tenant = pod['metadata'].get('labels', {}).get('tenant')
                if tenant in tenant_pods:
                    tenant_pods[tenant].append(pod)
                
                # Collect resource usage
                for container in pod['spec'].get('containers', []):
                    requests = container.get('resources', {}).get('requests', {})
                    if 'cpu' in requests:
                        cpu_val = requests['cpu']
                        if cpu_val.endswith('m'):
                            metrics['resource_usage']['cpu'] += float(cpu_val[:-1]) / 1000
                        else:
                            metrics['resource_usage']['cpu'] += float(cpu_val)
                    
                    if 'memory' in requests:
                        mem_val = requests['memory']
                        if mem_val.endswith('Mi'):
                            metrics['resource_usage']['memory'] += float(mem_val[:-2]) / 1024
                        elif mem_val.endswith('Gi'):
                            metrics['resource_usage']['memory'] += float(mem_val[:-2])
            
            # Calculate tenant-specific metrics
            for tenant, pods_list in tenant_pods.items():
                metrics['tenant_metrics'][tenant] = {
                    'pod_count': len(pods_list),
                    'running_pods': len([p for p in pods_list if p['status']['phase'] == 'Running']),
                    'avg_cpu': 0,
                    'avg_memory': 0,
                    'total_cpu': 0,
                    'total_memory': 0
                }
                
                if pods_list:
                    total_cpu = total_memory = 0
                    for pod in pods_list:
                        for container in pod['spec'].get('containers', []):
                            requests = container.get('resources', {}).get('requests', {})
                            if 'cpu' in requests:
                                cpu_val = requests['cpu']
                                if cpu_val.endswith('m'):
                                    total_cpu += float(cpu_val[:-1]) / 1000
                                else:
                                    total_cpu += float(cpu_val)
                            if 'memory' in requests:
                                mem_val = requests['memory']
                                if mem_val.endswith('Mi'):
                                    total_memory += float(mem_val[:-2]) / 1024
                                elif mem_val.endswith('Gi'):
                                    total_memory += float(mem_val[:-2])
                    
                    metrics['tenant_metrics'][tenant]['avg_cpu'] = total_cpu / len(pods_list)
                    metrics['tenant_metrics'][tenant]['avg_memory'] = total_memory / len(pods_list)
                    metrics['tenant_metrics'][tenant]['total_cpu'] = total_cpu
                    metrics['tenant_metrics'][tenant]['total_memory'] = total_memory
            
            # Calculate SLO violations
            resource_allocations = self.get_resource_allocations_from_pods(scheduler_name)
            slo_violations = self.calculate_slo_violations(scheduler_name, resource_allocations)
            
            metrics['slo_violations'] = slo_violations
            metrics['total_slo_violations'] = sum(1 for v in slo_violations.values() if v['violated'])
            
            severities = [v['severity'] for v in slo_violations.values()]
            metrics['avg_slo_severity'] = sum(severities) / len(severities) if severities else 0
            
            # Calculate resource efficiency
            total_cpu, total_memory = self.get_cluster_resources()
            metrics['resource_efficiency'] = (
                (metrics['resource_usage']['cpu'] / total_cpu) + 
                (metrics['resource_usage']['memory'] / total_memory)
            ) / 2 * 100
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to collect enhanced metrics: {e}")
            return {}
    
    def run_test_scenario(self, scheduler_name: str, config_file: str) -> Dict:
        """Run a complete test scenario for a scheduler"""
        logger.info(f"Running test scenario for {scheduler_name}")
        
        # Clean up first
        self.cleanup_deployments()
        
        # Apply configuration
        if not self.apply_config(config_file):
            return {}
        
        # Wait for pods to be ready
        if not self.wait_for_pods_ready(scheduler_name):
            logger.warning(f"Not all pods became ready for {scheduler_name}")
        
        # Collect enhanced metrics
        metrics = self.collect_enhanced_metrics(scheduler_name)
        
        # Add timestamp
        metrics['timestamp'] = datetime.now().isoformat()
        metrics['scheduler'] = scheduler_name
        
        return metrics
    
    def generate_enhanced_comparison_report(self):
        """Generate enhanced comparison report including SLO violations"""
        if not self.metrics['stackelberg'] or not self.metrics['regular']:
            logger.error("Missing metrics for comparison")
            return
        
        print("\n" + "="*80)
        print("ENHANCED SCHEDULER COMPARISON REPORT")
        print("="*80)
        
        # Pod deployment success
        print("\n📊 POD DEPLOYMENT SUCCESS:")
        stack_success = (self.metrics['stackelberg'].get('running_pods', 0) / 
                        max(self.metrics['stackelberg'].get('total_pods', 1), 1)) * 100
        regular_success = (self.metrics['regular'].get('running_pods', 0) / 
                          max(self.metrics['regular'].get('total_pods', 1), 1)) * 100
        
        print(f"  Stackelberg Scheduler: {stack_success:.1f}% ({self.metrics['stackelberg'].get('running_pods', 0)}/{self.metrics['stackelberg'].get('total_pods', 0)} pods)")
        print(f"  Regular Scheduler:     {regular_success:.1f}% ({self.metrics['regular'].get('running_pods', 0)}/{self.metrics['regular'].get('total_pods', 0)} pods)")
        
        # Resource utilization
        print("\n🔋 RESOURCE UTILIZATION:")
        print(f"  Stackelberg - CPU: {self.metrics['stackelberg'].get('resource_usage', {}).get('cpu', 0):.2f} cores, Memory: {self.metrics['stackelberg'].get('resource_usage', {}).get('memory', 0):.2f} GB")
        print(f"  Regular     - CPU: {self.metrics['regular'].get('resource_usage', {}).get('cpu', 0):.2f} cores, Memory: {self.metrics['regular'].get('resource_usage', {}).get('memory', 0):.2f} GB")
        
        # Resource efficiency
        print("\n⚡ RESOURCE EFFICIENCY:")
        print(f"  Stackelberg: {self.metrics['stackelberg'].get('resource_efficiency', 0):.1f}%")
        print(f"  Regular:     {self.metrics['regular'].get('resource_efficiency', 0):.1f}%")
        
        # SLO VIOLATIONS - NEW SECTION
        print("\n🚨 SLO VIOLATIONS ANALYSIS:")
        stack_slo = self.metrics['stackelberg'].get('slo_violations', {})
        regular_slo = self.metrics['regular'].get('slo_violations', {})
        
        print(f"  Total SLO Violations:")
        print(f"    Stackelberg: {self.metrics['stackelberg'].get('total_slo_violations', 0)}/3 tenants")
        print(f"    Regular:     {self.metrics['regular'].get('total_slo_violations', 0)}/3 tenants")
        
        print(f"  Average SLO Violation Severity:")
        print(f"    Stackelberg: {self.metrics['stackelberg'].get('avg_slo_severity', 0):.3f}")
        print(f"    Regular:     {self.metrics['regular'].get('avg_slo_severity', 0):.3f}")
        
        print("\n  Detailed SLO Status:")
        for tenant in ['web-app', 'data-processing', 'ml-training']:
            print(f"\n    {tenant.upper()}:")
            
            # Stackelberg SLO status
            if tenant in stack_slo:
                slo = stack_slo[tenant]
                status = "❌ VIOLATED" if slo['violated'] else "✅ MET"
                if tenant == 'web-app':
                    print(f"      Stackelberg: Response Time {slo['metric_value']:.1f}ms (threshold: {slo['threshold']:.1f}ms) {status}")
                elif tenant == 'data-processing':
                    print(f"      Stackelberg: Throughput {slo['metric_value']:.1f} jobs/h (threshold: {slo['threshold']:.1f}) {status}")
                else:
                    print(f"      Stackelberg: Training Time {slo['metric_value']:.1f}h (threshold: {slo['threshold']:.1f}h) {status}")
            
            # Regular SLO status
            if tenant in regular_slo:
                slo = regular_slo[tenant]
                status = "❌ VIOLATED" if slo['violated'] else "✅ MET"
                if tenant == 'web-app':
                    print(f"      Regular:     Response Time {slo['metric_value']:.1f}ms (threshold: {slo['threshold']:.1f}ms) {status}")
                elif tenant == 'data-processing':
                    print(f"      Regular:     Throughput {slo['metric_value']:.1f} jobs/h (threshold: {slo['threshold']:.1f}) {status}")
                else:
                    print(f"      Regular:     Training Time {slo['metric_value']:.1f}h (threshold: {slo['threshold']:.1f}h) {status}")
        
        # Tenant distribution
        print("\n👥 TENANT RESOURCE DISTRIBUTION:")
        for tenant in ['web-app', 'data-processing', 'ml-training']:
            stack_tenant = self.metrics['stackelberg'].get('tenant_metrics', {}).get(tenant, {})
            regular_tenant = self.metrics['regular'].get('tenant_metrics', {}).get(tenant, {})
            
            print(f"\n  {tenant.upper()}:")
            print(f"    Stackelberg: {stack_tenant.get('pod_count', 0)} pods, Total CPU: {stack_tenant.get('total_cpu', 0):.2f}, Total Memory: {stack_tenant.get('total_memory', 0):.2f} GB")
            print(f"    Regular:     {regular_tenant.get('pod_count', 0)} pods, Total CPU: {regular_tenant.get('total_cpu', 0):.2f}, Total Memory: {regular_tenant.get('total_memory', 0):.2f} GB")
        
        # Performance Summary
        print("\n📈 PERFORMANCE SUMMARY:")
        stack_better_efficiency = self.metrics['stackelberg'].get('resource_efficiency', 0) > self.metrics['regular'].get('resource_efficiency', 0)
        stack_better_slo = self.metrics['stackelberg'].get('total_slo_violations', 0) < self.metrics['regular'].get('total_slo_violations', 0)
        
        print(f"  Resource Efficiency Winner: {'🏆 Stackelberg' if stack_better_efficiency else '🏆 Regular'}")
        print(f"  SLO Compliance Winner: {'🏆 Stackelberg' if stack_better_slo else '🏆 Regular'}")
        
        if stack_better_efficiency and stack_better_slo:
            print("  🎉 Stackelberg scheduler outperforms regular scheduler in both metrics!")
        elif not stack_better_efficiency and not stack_better_slo:
            print("  ⚠️ Regular scheduler outperforms Stackelberg scheduler in both metrics!")
        else:
            print("  ⚖️ Mixed results - each scheduler has advantages in different areas")
    
    def create_enhanced_visualization(self):
        """Create enhanced comparison visualizations including SLO violations"""
        fig, ((ax1, ax2), (ax3, ax4), (ax5, ax6)) = plt.subplots(3, 2, figsize=(16, 18))
        
        schedulers = ['Stackelberg', 'Regular']
        colors = ['#2E8B57', '#4682B4']
        
        # 1. Pod Success Rate
        stack_success = (self.metrics['stackelberg'].get('running_pods', 0) / 
                        max(self.metrics['stackelberg'].get('total_pods', 1), 1)) * 100
        regular_success = (self.metrics['regular'].get('running_pods', 0) / 
                          max(self.metrics['regular'].get('total_pods', 1), 1)) * 100
        success_rates = [stack_success, regular_success]
        
        bars1 = ax1.bar(schedulers, success_rates, color=colors)
        ax1.set_title('Pod Deployment Success Rate', fontsize=14, fontweight='bold')
        ax1.set_ylabel('Success Rate (%)')
        ax1.set_ylim(0, 100)
        for i, v in enumerate(success_rates):
            ax1.text(i, v + 1, f'{v:.1f}%', ha='center', va='bottom', fontweight='bold')
        
        # 2. Resource Efficiency
        stack_efficiency = self.metrics['stackelberg'].get('resource_efficiency', 0)
        regular_efficiency = self.metrics['regular'].get('resource_efficiency', 0)
        efficiencies = [stack_efficiency, regular_efficiency]
        
        bars2 = ax2.bar(schedulers, efficiencies, color=colors)
        ax2.set_title('Resource Efficiency', fontsize=14, fontweight='bold')
        ax2.set_ylabel('Efficiency (%)')
        for i, v in enumerate(efficiencies):
            ax2.text(i, v + 0.5, f'{v:.1f}%', ha='center', va='bottom', fontweight='bold')
        
        # 3. SLO Violations
        stack_violations = self.metrics['stackelberg'].get('total_slo_violations', 0)
        regular_violations = self.metrics['regular'].get('total_slo_violations', 0)
        violations = [stack_violations, regular_violations]
        
        bars3 = ax3.bar(schedulers, violations, color=['#DC143C' if v > 0 else '#32CD32' for v in violations])
        ax3.set_title('Total SLO Violations', fontsize=14, fontweight='bold')
        ax3.set_ylabel('Number of SLO Violations')
        ax3.set_ylim(0, 3)
        for i, v in enumerate(violations):
            ax3.text(i, v + 0.05, f'{int(v)}', ha='center', va='bottom', fontweight='bold')
        
        # 4. SLO Violation Severity
        stack_severity = self.metrics['stackelberg'].get('avg_slo_severity', 0)
        regular_severity = self.metrics['regular'].get('avg_slo_severity', 0)
        severities = [stack_severity, regular_severity]
        
        bars4 = ax4.bar(schedulers, severities, color=['#FF6347' if s > 0.1 else '#90EE90' for s in severities])
        ax4.set_title('Average SLO Violation Severity', fontsize=14, fontweight='bold')
        ax4.set_ylabel('Severity Score')
        for i, v in enumerate(severities):
            ax4.text(i, v + 0.01, f'{v:.3f}', ha='center', va='bottom', fontweight='bold')
        
        # 5. CPU Allocation by Tenant
        tenants = ['web-app', 'data-processing', 'ml-training']
        stack_cpu = [self.metrics['stackelberg'].get('tenant_metrics', {}).get(t, {}).get('total_cpu', 0) for t in tenants]
        regular_cpu = [self.metrics['regular'].get('tenant_metrics', {}).get(t, {}).get('total_cpu', 0) for t in tenants]
        
        x = np.arange(len(tenants))
        width = 0.35
        
        bars5_1 = ax5.bar(x - width/2, stack_cpu, width, label='Stackelberg', color='#2E8B57')
        bars5_2 = ax5.bar(x + width/2, regular_cpu, width, label='Regular', color='#4682B4')
        ax5.set_title('Total CPU Allocation by Tenant', fontsize=14, fontweight='bold')
        ax5.set_ylabel('CPU Cores')
        ax5.set_xticks(x)
        ax5.set_xticklabels([t.replace('-', '\n') for t in tenants])
        ax5.legend()
        
        # Add value labels on CPU bars
        for bars in [bars5_1, bars5_2]:
            for bar in bars:
                height = bar.get_height()
                ax5.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                        f'{height:.2f}', ha='center', va='bottom', fontsize=10)
        
        # 6. Memory Allocation by Tenant
        stack_memory = [self.metrics['stackelberg'].get('tenant_metrics', {}).get(t, {}).get('total_memory', 0) for t in tenants]
        regular_memory = [self.metrics['regular'].get('tenant_metrics', {}).get(t, {}).get('total_memory', 0) for t in tenants]
        
        bars6_1 = ax6.bar(x - width/2, stack_memory, width, label='Stackelberg', color='#2E8B57')
        bars6_2 = ax6.bar(x + width/2, regular_memory, width, label='Regular', color='#4682B4')
        ax6.set_title('Total Memory Allocation by Tenant', fontsize=14, fontweight='bold')
        ax6.set_ylabel('Memory (GB)')
        ax6.set_xticks(x)
        ax6.set_xticklabels([t.replace('-', '\n') for t in tenants])
        ax6.legend()
        
        # Add value labels on Memory bars
        for bars in [bars6_1, bars6_2]:
            for bar in bars:
                height = bar.get_height()
                ax6.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                        f'{height:.2f}', ha='center', va='bottom', fontsize=10)
        
        plt.tight_layout()
        plt.savefig('enhanced_scheduler_comparison.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        logger.info("Enhanced visualization saved as 'enhanced_scheduler_comparison.png'")
    
    def create_slo_detail_visualization(self):
        """Create detailed SLO violation visualization"""
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6))
        
        schedulers = ['Stackelberg', 'Regular']
        
        # Web App Response Time
        stack_web = self.metrics['stackelberg'].get('slo_violations', {}).get('web-app', {})
        regular_web = self.metrics['regular'].get('slo_violations', {}).get('web-app', {})
        
        web_values = [stack_web.get('metric_value', 0), regular_web.get('metric_value', 0)]
        web_threshold = stack_web.get('threshold', 100)  # Should be same for both
        
        bars1 = ax1.bar(schedulers, web_values, color=['#DC143C' if v > web_threshold else '#32CD32' for v in web_values])
        ax1.axhline(y=web_threshold, color='red', linestyle='--', alpha=0.7, label=f'SLO Threshold: {web_threshold}ms')
        ax1.set_title('Web App Response Time', fontsize=14, fontweight='bold')
        ax1.set_ylabel('Response Time (ms)')
        ax1.legend()
        for i, v in enumerate(web_values):
            ax1.text(i, v + 5, f'{v:.1f}ms', ha='center', va='bottom', fontweight='bold')
        
        # Data Processing Throughput
        stack_data = self.metrics['stackelberg'].get('slo_violations', {}).get('data-processing', {})
        regular_data = self.metrics['regular'].get('slo_violations', {}).get('data-processing', {})
        
        data_values = [stack_data.get('metric_value', 0), regular_data.get('metric_value', 0)]
        data_threshold = stack_data.get('threshold', 500)
        
        bars2 = ax2.bar(schedulers, data_values, color=['#32CD32' if v >= data_threshold else '#DC143C' for v in data_values])
        ax2.axhline(y=data_threshold, color='red', linestyle='--', alpha=0.7, label=f'SLO Threshold: {data_threshold} jobs/h')
        ax2.set_title('Data Processing Throughput', fontsize=14, fontweight='bold')
        ax2.set_ylabel('Throughput (jobs/hour)')
        ax2.legend()
        for i, v in enumerate(data_values):
            ax2.text(i, v + 20, f'{v:.1f}', ha='center', va='bottom', fontweight='bold')
        
        # ML Training Time
        stack_ml = self.metrics['stackelberg'].get('slo_violations', {}).get('ml-training', {})
        regular_ml = self.metrics['regular'].get('slo_violations', {}).get('ml-training', {})
        
        ml_values = [stack_ml.get('metric_value', 0), regular_ml.get('metric_value', 0)]
        ml_threshold = stack_ml.get('threshold', 15)
        
        bars3 = ax3.bar(schedulers, ml_values, color=['#32CD32' if v <= ml_threshold else '#DC143C' for v in ml_values])
        ax3.axhline(y=ml_threshold, color='red', linestyle='--', alpha=0.7, label=f'SLO Threshold: {ml_threshold}h')
        ax3.set_title('ML Training Time', fontsize=14, fontweight='bold')
        ax3.set_ylabel('Training Time (hours)')
        ax3.legend()
        for i, v in enumerate(ml_values):
            ax3.text(i, v + 0.5, f'{v:.1f}h', ha='center', va='bottom', fontweight='bold')
        
        plt.tight_layout()
        plt.savefig('slo_details_comparison.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        logger.info("SLO details visualization saved as 'slo_details_comparison.png'")
    
    def save_detailed_metrics(self):
        """Save detailed metrics to JSON and CSV files"""
        # Save JSON
        with open('enhanced_scheduler_metrics.json', 'w') as f:
            json.dump(self.metrics, f, indent=2)
        
        # Create CSV summary
        summary_data = []
        for scheduler in ['stackelberg', 'regular']:
            if scheduler in self.metrics:
                m = self.metrics[scheduler]
                row = {
                    'scheduler': scheduler,
                    'running_pods': m.get('running_pods', 0),
                    'total_pods': m.get('total_pods', 0),
                    'success_rate': (m.get('running_pods', 0) / max(m.get('total_pods', 1), 1)) * 100,
                    'total_cpu': m.get('resource_usage', {}).get('cpu', 0),
                    'total_memory': m.get('resource_usage', {}).get('memory', 0),
                    'resource_efficiency': m.get('resource_efficiency', 0),
                    'total_slo_violations': m.get('total_slo_violations', 0),
                    'avg_slo_severity': m.get('avg_slo_severity', 0)
                }
                
                # Add tenant-specific data
                for tenant in ['web-app', 'data-processing', 'ml-training']:
                    tenant_data = m.get('tenant_metrics', {}).get(tenant, {})
                    row[f'{tenant}_pods'] = tenant_data.get('pod_count', 0)
                    row[f'{tenant}_cpu'] = tenant_data.get('total_cpu', 0)
                    row[f'{tenant}_memory'] = tenant_data.get('total_memory', 0)
                    
                    # Add SLO data
                    slo_data = m.get('slo_violations', {}).get(tenant, {})
                    row[f'{tenant}_slo_violated'] = slo_data.get('violated', False)
                    row[f'{tenant}_slo_severity'] = slo_data.get('severity', 0)
                    row[f'{tenant}_metric_value'] = slo_data.get('metric_value', 0)
                
                summary_data.append(row)
        
        df = pd.DataFrame(summary_data)
        df.to_csv('scheduler_comparison_summary.csv', index=False)
        
        logger.info("Detailed metrics saved to 'enhanced_scheduler_metrics.json' and 'scheduler_comparison_summary.csv'")

def main():
    """Main execution function"""
    comparison = EnhancedSchedulerComparison()
    
    print("="*80)
    print("ENHANCED KUBERNETES SCHEDULER COMPARISON")
    print("="*80)
    print(f"Configuration loaded from: {comparison.config_file}")
    print(f"Parameters loaded: {len(comparison.config_params)}")
    print("="*80)
    
    # Test Stackelberg Scheduler
    logger.info("Testing Stackelberg Scheduler...")
    comparison.metrics['stackelberg'] = comparison.run_test_scenario(
        'stackelberg-scheduler', 
        'test/stackelberg-test.yaml'
    )
    
    # Wait between tests
    logger.info("Waiting between tests...")
    time.sleep(60)
    
    # Test Regular Scheduler
    logger.info("Testing Regular Scheduler...")
    comparison.metrics['regular'] = comparison.run_test_scenario(
        'default-scheduler',
        'test/regular-test.yaml'
    )
    
    # Generate enhanced reports and visualizations
    comparison.generate_enhanced_comparison_report()
    comparison.create_enhanced_visualization()
    comparison.create_slo_detail_visualization()
    comparison.save_detailed_metrics()
    
    logger.info("Enhanced comparison complete!")
    logger.info("Check the following files:")
    logger.info("  - enhanced_scheduler_metrics.json (detailed metrics)")
    logger.info("  - scheduler_comparison_summary.csv (summary table)")
    logger.info("  - enhanced_scheduler_comparison.png (main comparison charts)")
    logger.info("  - slo_details_comparison.png (detailed SLO analysis)")

if __name__ == "__main__":
    main()