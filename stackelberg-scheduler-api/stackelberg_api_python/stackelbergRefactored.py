import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize, minimize_scalar
import pandas as pd
from dataclasses import dataclass
from typing import List, Tuple, Dict
import seaborn as sns


@dataclass
class ClusterResources:
    def __init__(self, params: Dict[str, float]):
        self.total_cpu = params.get("total_cpu", 32)
        self.total_memory = params.get("total_memory", 128)

@dataclass
class Tenant:
    name: str
    max_response_time: float = None  # ms
    min_throughput: float = None  # jobs/hour
    max_training_time: float = None  # hours
    budget: float = 1000.0
    min_cpu: float = 1.0  # per replica
    min_memory: float = 4.0  # per replica
    desired_replicas: int = None
    min_replicas: int = None
    priority: float = 1.0  # Higher priority gets resources first

class KubernetesSchedulerSimulator:
    def __init__(self, cluster: ClusterResources, params: Dict[str, float]):
        self.cluster = cluster
        self.params = params  # ✅ Store incoming params for later use
        self.tenant_config = self._load_tenant_config()
        self.tenants = self._setup_tenants()

    def _load_tenant_config(self) -> Dict:
        """Load tenant configurations from provided params (no Excel)"""
        try:
            params = self.params

            return {
                'web_app': {
                    'max_response_time': params.get('web_app_max_response_time', 52.5),
                    'budget': params.get('web_app_budget', 800),
                    'min_cpu': params.get('web_app_min_cpu', 2),
                    'min_memory': params.get('web_app_min_memory', 8),
                    'desired_replicas': params.get('web_app_desired_replicas', 1),
                    'min_replicas': params.get('web_app_min_replicas', 1),
                    'priority': params.get('web_app_priority', 1.0),
                },
                'data_processing': {
                    'min_throughput': params.get('data_processing_min_throughput', 1000),
                    'budget': params.get('data_processing_budget', 1200),
                    'min_cpu': params.get('data_processing_min_cpu', 1),
                    'min_memory': params.get('data_processing_min_memory', 4),
                    'desired_replicas': params.get('data_processing_desired_replicas', 1),
                    'min_replicas': params.get('data_processing_min_replicas', 1),
                    'priority': params.get('data_processing_priority', 0.8),
                },
                'ml_training': {
                    'max_training_time': params.get('ml_training_max_training_time', 8),
                    'budget': params.get('ml_training_budget', 1500),
                    'min_cpu': params.get('ml_training_min_cpu', 4),
                    'min_memory': params.get('ml_training_min_memory', 16),
                    'desired_replicas': params.get('ml_training_desired_replicas', 1),
                    'min_replicas': params.get('ml_training_min_replicas', 1),
                    'priority': params.get('ml_training_priority', 1.2),
                }
            }
        except Exception as e:
            print(f"❌ Error loading tenant config: {e}")
            return {}

    def _setup_tenants(self) -> List[Tenant]:
        """Create tenant objects using configured parameters"""
        return [
            Tenant(
                name="Web-App",
                max_response_time=self.tenant_config['web_app']['max_response_time'],
                budget=self.tenant_config['web_app']['budget'],
                min_cpu=self.tenant_config['web_app']['min_cpu'],
                min_memory=self.tenant_config['web_app']['min_memory'],
                desired_replicas=self.tenant_config['web_app']['desired_replicas'],
                min_replicas=self.tenant_config['web_app']['min_replicas'],
                priority=self.tenant_config['web_app']['priority'],
            ),
            Tenant(
                name="Data-Processing",
                min_throughput=self.tenant_config['data_processing']['min_throughput'],
                budget=self.tenant_config['data_processing']['budget'],
                min_cpu=self.tenant_config['data_processing']['min_cpu'],
                min_memory=self.tenant_config['data_processing']['min_memory'],
                desired_replicas=self.tenant_config['data_processing']['desired_replicas'],
                min_replicas=self.tenant_config['data_processing']['min_replicas'],
                priority=self.tenant_config['data_processing']['priority'],
            ),
            Tenant(
                name="ML-Training",
                max_training_time=self.tenant_config['ml_training']['max_training_time'],
                budget=self.tenant_config['ml_training']['budget'],
                min_cpu=self.tenant_config['ml_training']['min_cpu'],
                min_memory=self.tenant_config['ml_training']['min_memory'],
                desired_replicas=self.tenant_config['ml_training']['desired_replicas'],
                min_replicas=self.tenant_config['ml_training']['min_replicas'],
                priority=self.tenant_config['ml_training']['priority'],
            )
        ]

class StackelbergScheduler(KubernetesSchedulerSimulator):
    def __init__(self, cluster: ClusterResources, params: Dict[str, float]):
        self.params = params
        self.alpha1 = params.get("alpha1", 0.5)
        self.alpha2 = params.get("alpha2", 0.3)
        self.alpha3 = params.get("alpha3", 0.2)
        super().__init__(cluster, params)

    def tenant_a_utility(self, cpu_per_replica: float, memory_per_replica: float, replicas: int) -> float:
        """Web Application utility function with configurable parameters."""
        try:
            # Read the Excel file
            params = self.params
            
            # Extract parameters (with defaults if missing)
            cpu_norm = params.get('cpu_norm', 5)
            memory_norm = params.get('memory_norm', 20)
            base_exponent = params.get('base_exponent', 0.7)
            rt_const1 = params.get('rt_const1', 50)
            rt_const2 = params.get('rt_const2', 500)
            rt_exponent = params.get('rt_exponent', 0.3)
            latency_thresh = params.get('latency_thresh', 52.5)
            latency_penalty = params.get('latency_penalty', 100)

            # Calculate utility per replica
            base_utility_per_replica = 200 * min(cpu_per_replica / cpu_norm, memory_per_replica / memory_norm) ** base_exponent
            response_time = rt_const1 + rt_const2 / (cpu_per_replica * memory_per_replica ** rt_exponent)
            penalty_per_replica = max(0, latency_penalty * (response_time - latency_thresh)) \
                    if response_time > latency_thresh else 0

            # Total utility scales with replicas but with diminishing returns
            total_utility = (base_utility_per_replica - penalty_per_replica) * (replicas ** 0.8)
            return total_utility
        except Exception as e:
            print(f"Error reading config: {e}. Using hardcoded defaults.")
            # Fallback to original values
            base_utility_per_replica = 200 * min(cpu_per_replica / 5, memory_per_replica / 20) ** 0.7
            response_time = 50 + 500 / (cpu_per_replica * memory_per_replica ** 0.3)
            penalty_per_replica = max(0, 100 * (response_time - 52.5)) if response_time > 52.5 else 0
            total_utility = (base_utility_per_replica - penalty_per_replica) * (replicas ** 0.8)
            return total_utility

    def tenant_b_utility(self, cpu_per_replica: float, memory_per_replica: float, replicas: int) -> float:
        """Data Processing utility function with configurable parameters."""
        try:
            params = self.params
            

            base_coeff = params.get('tenant_b_base_coeff', 80)
            memory_exp1 = params.get('tenant_b_memory_exp1', 0.6)
            base_exp = params.get('tenant_b_base_exp', 0.8)
            throughput_coeff = params.get('tenant_b_throughput_coeff', 15)
            throughput_cpu_exp = params.get('tenant_b_throughput_cpu_exp', 0.8)
            throughput_mem_exp = params.get('tenant_b_throughput_mem_exp', 0.4)
            queue_penalty_thresh = params.get('tenant_b_queue_penalty_thresh', 1000)
            queue_penalty_coeff = params.get('tenant_b_queue_penalty_coeff', 2)

            # Calculate utility with logarithmic scaling to prevent extreme values
            base_utility_per_replica = base_coeff * np.log(1 + (cpu_per_replica * memory_per_replica ** memory_exp1) ** base_exp)

            actual_throughput_per_replica = throughput_coeff * cpu_per_replica ** throughput_cpu_exp * memory_per_replica ** throughput_mem_exp
            required_throughput_per_replica = queue_penalty_thresh / max(replicas, 1)  # Avoid division by zero

            if actual_throughput_per_replica < required_throughput_per_replica:
                penalty_per_replica = queue_penalty_coeff * (required_throughput_per_replica - actual_throughput_per_replica)
            else:
                penalty_per_replica = 0

            # Throughput scales with replicas but with diminishing returns
            total_utility = (base_utility_per_replica - penalty_per_replica) * (replicas ** 0.8)
            return total_utility

        except Exception as e:
            print(f"Error reading Tenant B config: {e}. Using hardcoded defaults.")
            # Fallback with logarithmic scaling
            base_utility_per_replica = 80 * np.log(1 + (cpu_per_replica * memory_per_replica ** 0.6) ** 0.8)
            actual_throughput_per_replica = 15 * cpu_per_replica ** 0.8 * memory_per_replica ** 0.4
            penalty_per_replica = max(0, 2 * (1000/max(replicas, 1) - actual_throughput_per_replica))
            total_utility = (base_utility_per_replica - penalty_per_replica) * (replicas ** 0.8)
            return total_utility

    def tenant_c_utility(self, cpu_per_replica: float, memory_per_replica: float, replicas: int) -> float:
        """ML Training utility function with configurable parameters."""
        try:
            # Read the Excel file
            params = self.params
            

            # Extract parameters (with defaults if missing)
            base_coeff = params.get('tenant_c_base_coeff', 120)
            memory_exp1 = params.get('tenant_c_memory_exp1', 0.5)
            log_const = params.get('tenant_c_log_const', 1)
            training_cpu_exp = params.get('tenant_c_training_cpu_exp', 0.7)
            training_mem_exp = params.get('tenant_c_training_mem_exp', 0.3)
            time_penalty_thresh = params.get('tenant_c_time_penalty_thresh', 8)
            time_penalty_coeff = params.get('tenant_c_time_penalty_coeff', 40)

            # Calculate utility
            base_utility_per_replica = base_coeff * np.log(log_const + cpu_per_replica ** 0.9 * memory_per_replica ** memory_exp1)
            training_time = 20 / (cpu_per_replica ** training_cpu_exp * memory_per_replica ** training_mem_exp)
            penalty_per_replica = max(0, time_penalty_coeff * (training_time - time_penalty_thresh)) \
                    if training_time > time_penalty_thresh else 0

            # Training time benefit scales with replicas (parallel training)
            total_utility = (base_utility_per_replica - penalty_per_replica) * (replicas ** 0.9)
            return total_utility

        except Exception as e:
            print(f"Error reading Tenant C config: {e}. Using hardcoded defaults.")
            # Fallback to original values
            base_utility_per_replica = 120 * np.log(1 + cpu_per_replica ** 0.9 * memory_per_replica ** 0.5)
            training_time = 20 / (cpu_per_replica ** 0.7 * memory_per_replica ** 0.3)
            penalty_per_replica = max(0, 40 * (training_time - 8)) if training_time > 8 else 0
            total_utility = (base_utility_per_replica - penalty_per_replica) * (replicas ** 0.9)
            return total_utility

    def get_tenant_performance_metrics(self, tenant_idx: int, cpu_per_replica: float, memory_per_replica: float, replicas: int) -> Dict:
        def is_close(a, b, rel_tol=1e-5, abs_tol=1e-5):
          return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)
        try:
            # Read the Excel file once (same as utility functions)
            params = self.params
            

            metrics = {}
            total_cpu = cpu_per_replica * replicas
            total_memory = memory_per_replica * replicas

            if tenant_idx == 0:  # Web App (Tenant A)
                rt_const1 = params.get('rt_const1', 50)
                rt_const2 = params.get('rt_const2', 500)
                rt_exponent = params.get('rt_exponent', 0.3)
                latency_thresh = params.get('latency_thresh', 52.5)

                response_time = rt_const1 + rt_const2 / (cpu_per_replica * memory_per_replica ** rt_exponent)
                metrics['response_time'] = response_time
                metrics['slo_met'] = response_time <= 52.5 or is_close(response_time, 52.5)
                metrics['slo_violation_severity'] = max(0, (response_time - latency_thresh) / latency_thresh) \
                                                  if response_time > latency_thresh else 0
                metrics['replicas'] = replicas
                metrics['total_cpu'] = total_cpu
                metrics['total_memory'] = total_memory

            elif tenant_idx == 1:  # Data Processing (Tenant B)
                throughput_coeff = params.get('tenant_b_throughput_coeff', 15)
                throughput_cpu_exp = params.get('tenant_b_throughput_cpu_exp', 0.8)
                throughput_mem_exp = params.get('tenant_b_throughput_mem_exp', 0.4)
                queue_penalty_thresh = params.get('tenant_b_queue_penalty_thresh', 1000)

                throughput = throughput_coeff * cpu_per_replica ** throughput_cpu_exp * memory_per_replica ** throughput_mem_exp * replicas
                metrics['throughput'] = throughput
                metrics['slo_met'] = throughput >= queue_penalty_thresh
                metrics['slo_violation_severity'] = max(0, (queue_penalty_thresh - throughput) / queue_penalty_thresh) \
                                                  if throughput < queue_penalty_thresh else 0
                metrics['replicas'] = replicas
                metrics['total_cpu'] = total_cpu
                metrics['total_memory'] = total_memory

            else:  # ML Training (Tenant C)
                training_cpu_exp = params.get('tenant_c_training_cpu_exp', 0.7)
                training_mem_exp = params.get('tenant_c_training_mem_exp', 0.3)
                time_penalty_thresh = params.get('tenant_c_time_penalty_thresh', 8)

                training_time = 20 / (cpu_per_replica ** training_cpu_exp * memory_per_replica ** training_mem_exp)
                metrics['training_time'] = training_time
                metrics['slo_met'] = training_time <= time_penalty_thresh
                metrics['slo_violation_severity'] = max(0, (training_time - time_penalty_thresh) / time_penalty_thresh) \
                                                  if training_time > time_penalty_thresh else 0
                metrics['replicas'] = replicas
                metrics['total_cpu'] = total_cpu
                metrics['total_memory'] = total_memory

            return metrics

        except Exception as e:
            print(f"Error reading config: {e}. Using hardcoded defaults.")
            # Fallback to original implementation
            metrics = {}
            total_cpu = cpu_per_replica * replicas
            total_memory = memory_per_replica * replicas

            if tenant_idx == 0:
                response_time = 50 + 500 / (cpu_per_replica * memory_per_replica ** 0.3)
                metrics['response_time'] = response_time
                metrics['slo_met'] = response_time <= 52.5
                metrics['slo_violation_severity'] = max(0, (response_time - 52.5) / 52.5) if response_time > 200 else 0
                metrics['replicas'] = replicas
                metrics['total_cpu'] = total_cpu
                metrics['total_memory'] = total_memory
            elif tenant_idx == 1:
                throughput = 15 * cpu_per_replica ** 0.8 * memory_per_replica ** 0.4 * replicas
                metrics['throughput'] = throughput
                metrics['slo_met'] = throughput >= 1000
                metrics['slo_violation_severity'] = max(0, (1000 - throughput) / 1000) if throughput < 1000 else 0
                metrics['replicas'] = replicas
                metrics['total_cpu'] = total_cpu
                metrics['total_memory'] = total_memory
            else:
                training_time = 20 / (cpu_per_replica ** 0.7 * memory_per_replica ** 0.3)
                metrics['training_time'] = training_time
                metrics['slo_met'] = training_time <= 8
                metrics['slo_violation_severity'] = max(0, (training_time - 8) / 8) if training_time > 8 else 0
                metrics['replicas'] = replicas
                metrics['total_cpu'] = total_cpu
                metrics['total_memory'] = total_memory
            return metrics

    def tenant_optimize(self, tenant_idx: int, p_cpu: float, p_memory: float, verbose: bool = False) -> Tuple[float, float, int, Dict]:
        """Optimize resource allocation for a specific tenant with detailed logging"""
        tenant = self.tenants[tenant_idx]

        def objective(x):
            cpu_per_replica, memory_per_replica, replicas = x[0], x[1], x[2]
            total_cpu = cpu_per_replica * replicas
            total_memory = memory_per_replica * replicas

            if tenant_idx == 0:
                utility = self.tenant_a_utility(cpu_per_replica, memory_per_replica, replicas)
            elif tenant_idx == 1:
                utility = self.tenant_b_utility(cpu_per_replica, memory_per_replica, replicas)
            else:
                utility = self.tenant_c_utility(cpu_per_replica, memory_per_replica, replicas)

            total_cost = p_cpu * total_cpu + p_memory * total_memory
            net_utility = utility - total_cost
            return -net_utility  # Negative because we minimize

        # Constraints
        constraints = [
            {'type': 'ineq', 'fun': lambda x: x[0] - tenant.min_cpu},  # min CPU per replica
            {'type': 'ineq', 'fun': lambda x: x[1] - tenant.min_memory},  # min memory per replica
            {'type': 'ineq', 'fun': lambda x: x[2] - tenant.min_replicas},  # min replicas
            {'type': 'ineq', 'fun': lambda x: tenant.budget - (p_cpu * x[0] * x[2] + p_memory * x[1] * x[2])}  # budget
        ]

        bounds = [
            (tenant.min_cpu, self.cluster.total_cpu),
            (tenant.min_memory, self.cluster.total_memory),
            (tenant.min_replicas, tenant.desired_replicas)  # Can't exceed desired replicas
        ]

        # Initial guess
        x0 = [tenant.min_cpu * 2, tenant.min_memory * 2, tenant.min_replicas]

        result = minimize(objective, x0, method='SLSQP', bounds=bounds, constraints=constraints)

        if result.success:
            optimal_cpu_per_replica, optimal_memory_per_replica, optimal_replicas = result.x[0], result.x[1], int(round(result.x[2]))
        else:
            optimal_cpu_per_replica, optimal_memory_per_replica, optimal_replicas = tenant.min_cpu, tenant.min_memory, tenant.min_replicas

        # Calculate total resources and utilities
        total_cpu = optimal_cpu_per_replica * optimal_replicas
        total_memory = optimal_memory_per_replica * optimal_replicas

        if tenant_idx == 0:
            gross_utility = self.tenant_a_utility(optimal_cpu_per_replica, optimal_memory_per_replica, optimal_replicas)
        elif tenant_idx == 1:
            gross_utility = self.tenant_b_utility(optimal_cpu_per_replica, optimal_memory_per_replica, optimal_replicas)
        else:
            gross_utility = self.tenant_c_utility(optimal_cpu_per_replica, optimal_memory_per_replica, optimal_replicas)

        total_cost = p_cpu * total_cpu + p_memory * total_memory
        net_utility = gross_utility - total_cost

        # Get performance metrics
        performance_metrics = self.get_tenant_performance_metrics(tenant_idx, optimal_cpu_per_replica, optimal_memory_per_replica, optimal_replicas)

        optimization_details = {
            'gross_utility': gross_utility,
            'total_cost': total_cost,
            'net_utility': net_utility,
            'budget_used_pct': (total_cost / tenant.budget) * 100,
            'performance_metrics': performance_metrics,
            'optimization_success': result.success
        }

        return optimal_cpu_per_replica, optimal_memory_per_replica, optimal_replicas, optimization_details

    def jains_fairness_index(self, values):
        """Calculate Jain's Fairness Index for resource allocations"""
        values = np.array(values)
        values = np.maximum(values, 0.01)  # Ensure no zero values
        numerator = np.sum(values) ** 2
        denominator = len(values) * np.sum(values ** 2)
        return numerator / denominator if denominator > 0 else 1.0

    def platform_utility(self, allocations: List[Tuple[float, float, int]],
                     p_cpu: float, p_memory: float) -> Tuple[float, Dict]:
        """Calculate platform utility with detailed breakdown"""
        total_cpu_used = sum(alloc[0] * alloc[2] for alloc in allocations)  # cpu_per_replica * replicas
        total_memory_used = sum(alloc[1] * alloc[2] for alloc in allocations)  # memory_per_replica * replicas

        # Utilization
        cpu_utilization = total_cpu_used / self.cluster.total_cpu
        memory_utilization = total_memory_used / self.cluster.total_memory
        utilization = (cpu_utilization + memory_utilization) / 2

        # Fairness using Jain's index
        cpu_allocations = [alloc[0] * alloc[2] for alloc in allocations]  # total cpu per tenant
        memory_allocations = [alloc[1] * alloc[2] for alloc in allocations]  # total memory per tenant

        cpu_fairness = self.jains_fairness_index(cpu_allocations)
        memory_fairness = self.jains_fairness_index(memory_allocations)
        fairness = (cpu_fairness + memory_fairness) / 2

        # SLO violations with severity scoring
        slo_violation_score = 0
        slo_details = []

        for i, (cpu_per_replica, memory_per_replica, replicas) in enumerate(allocations):
            metrics = self.get_tenant_performance_metrics(i, cpu_per_replica, memory_per_replica, replicas)
            slo_violation_score += metrics['slo_violation_severity']
            slo_details.append({
                'tenant': self.tenants[i].name,
                'slo_met': metrics['slo_met'],
                'violation_severity': metrics['slo_violation_severity'],
                'metrics': metrics
            })

        platform_util = (self.alpha1 * utilization +
                         self.alpha2 * fairness -
                         self.alpha3 * slo_violation_score / 3)

        breakdown = {
            'utilization': utilization,
            'cpu_utilization': cpu_utilization,
            'memory_utilization': memory_utilization,
            'fairness': fairness,
            'cpu_fairness': cpu_fairness,
            'memory_fairness': memory_fairness,
            'slo_violation_score': slo_violation_score,
            'slo_details': slo_details,
            'total_cpu_used': total_cpu_used,
            'total_memory_used': total_memory_used,
            'revenue': p_cpu * total_cpu_used + p_memory * total_memory_used
        }

        return platform_util, breakdown

    # --- ADDED FROM CODE 2: Robust fallback handling ---
    def _evaluate_iteration_quality(self, allocations: List[Tuple[float, float, int]], 
                                   platform_breakdown: Dict) -> Tuple[int, float, float, float]:
        slo_violations_count = 0
        response_time = float('inf')
        throughput = 0
        training_time = float('inf')
        
        for i, slo_detail in enumerate(platform_breakdown['slo_details']):
            if not slo_detail['slo_met']:
                slo_violations_count += 1
                
            metrics = slo_detail['metrics']
            if i == 0:
                response_time = metrics.get('response_time', float('inf'))
            elif i == 1:
                throughput = metrics.get('throughput', 0)
            else:
                training_time = metrics.get('training_time', float('inf'))
                
        return slo_violations_count, response_time, throughput, training_time

    def _select_best_iteration(self, history: Dict, verbose: bool = True) -> Tuple[List, Tuple, Dict, int]:
        if not history['allocations']:
            if verbose:
                print("⚠️ No valid iterations found in history")
            return None, None, None, -1
            
        best_allocation = None
        best_prices = None
        best_details = None
        best_iteration_index = -1
        
        min_slo_violations = float('inf')
        best_response_time = float('inf')
        best_throughput = 0
        best_training_time = float('inf')
        
        if verbose:
            print("\n🔍 ANALYZING ITERATIONS FOR BEST SLO PERFORMANCE:")
            print("=" * 80)
        
        for i, (allocation, prices, breakdown) in enumerate(zip(
            history['allocations'], 
            history['prices'], 
            history['platform_details']
        )):
            slo_violations, response_time, throughput, training_time = self._evaluate_iteration_quality(
                allocation, breakdown
            )
            
            if verbose:
                print(f"Iteration {i+1}:")
                print(f"  SLO Violations: {slo_violations}/3")
                print(f"  Response Time: {response_time:.1f}ms")
                print(f"  Throughput: {throughput:.1f} jobs/h") 
                print(f"  Training Time: {training_time:.1f}h")
                
            is_better = False
            
            if slo_violations < min_slo_violations:
                is_better = True
                if verbose:
                    print(f"  ✅ BETTER - Fewer SLO violations ({slo_violations} vs {min_slo_violations})")
                    
            elif slo_violations == min_slo_violations:
                performance_score_current = (
                    -response_time + 
                    throughput * 0.01 + 
                    -training_time
                )
                
                performance_score_best = (
                    -best_response_time +
                    best_throughput * 0.01 + 
                    -best_training_time
                )
                
                if performance_score_current > performance_score_best:
                    is_better = True
                    if verbose:
                        print(f"  ✅ BETTER - Better performance metrics (score: {performance_score_current:.2f} vs {performance_score_best:.2f})")
                        
            if is_better:
                min_slo_violations = slo_violations
                best_response_time = response_time
                best_throughput = throughput  
                best_training_time = training_time
                best_allocation = allocation.copy()
                best_prices = prices
                best_details = breakdown.copy()
                best_iteration_index = i
                
            if verbose:
                print()
                
        if verbose and best_iteration_index >= 0:
            print(f"🎯 SELECTED BEST ITERATION: {best_iteration_index + 1}")
            print(f"   SLO Violations: {min_slo_violations}/3")
            print(f"   Response Time: {best_response_time:.1f}ms")
            print(f"   Throughput: {best_throughput:.1f} jobs/h")
            print(f"   Training Time: {best_training_time:.1f}h")
            print("=" * 80)
            
        return best_allocation, best_prices, best_details, best_iteration_index

    def _redistribute_resources(self, allocations: List[Tuple[float, float, int]], 
                               total_cpu_used: float, 
                               total_memory_used: float) -> List[Tuple[float, float, int]]:
        """Redistribute resources to fit within cluster constraints"""
        # Calculate resource deficit
        cpu_deficit = max(0, total_cpu_used - self.cluster.total_cpu)
        memory_deficit = max(0, total_memory_used - self.cluster.total_memory)
        
        if cpu_deficit <= 0 and memory_deficit <= 0:
            return allocations
        
        # Sort tenants by priority (lowest priority first)
        tenant_indices = sorted(range(len(self.tenants)), 
                               key=lambda i: self.tenants[i].priority, 
                               reverse=False)
        
        new_allocations = [alloc for alloc in allocations]
        
        # First pass: reduce replicas for low-priority tenants
        for idx in tenant_indices:
            if cpu_deficit <= 0 and memory_deficit <= 0:
                break
                
            cpu, mem, reps = new_allocations[idx]
            tenant = self.tenants[idx]
            
            # Can we reduce replicas?
            if reps > tenant.min_replicas:
                # Reduce by one replica
                new_reps = reps - 1
                cpu_reduction = cpu * (reps - new_reps)
                mem_reduction = mem * (reps - new_reps)
                
                # Only apply if it helps reduce the deficit
                if cpu_reduction > 0 or mem_reduction > 0:
                    new_allocations[idx] = (cpu, mem, new_reps)
                    total_cpu_used -= cpu_reduction
                    total_memory_used -= mem_reduction
                    cpu_deficit = max(0, total_cpu_used - self.cluster.total_cpu)
                    memory_deficit = max(0, total_memory_used - self.cluster.total_memory)
        
        # Second pass: reduce resources per replica if still over capacity
        for idx in tenant_indices:
            if cpu_deficit <= 0 and memory_deficit <= 0:
                break
                
            cpu, mem, reps = new_allocations[idx]
            tenant = self.tenants[idx]
            
            # Calculate how much we can reduce
            max_cpu_reduction = cpu - tenant.min_cpu
            max_mem_reduction = mem - tenant.min_memory
            
            # Determine reduction ratios based on deficits
            cpu_reduction_ratio = min(0.2, cpu_deficit / (cpu * reps)) if cpu * reps > 0 else 0
            mem_reduction_ratio = min(0.2, memory_deficit / (mem * reps)) if mem * reps > 0 else 0
            reduction_ratio = max(cpu_reduction_ratio, mem_reduction_ratio)
            
            if reduction_ratio > 0:
                new_cpu = max(tenant.min_cpu, cpu * (1 - reduction_ratio))
                new_mem = max(tenant.min_memory, mem * (1 - reduction_ratio))
                
                cpu_reduction = (cpu - new_cpu) * reps
                mem_reduction = (mem - new_mem) * reps
                
                new_allocations[idx] = (new_cpu, new_mem, reps)
                total_cpu_used -= cpu_reduction
                total_memory_used -= mem_reduction
                cpu_deficit = max(0, total_cpu_used - self.cluster.total_cpu)
                memory_deficit = max(0, total_memory_used - self.cluster.total_memory)
                
        return new_allocations

    def stackelberg_equilibrium(self, max_iterations: int = 25, verbose: bool = True) -> Dict:
        """Find Stackelberg equilibrium with detailed iteration logging and robust fallback handling"""
        try:
            # Read the Excel file
            params = self.params
            
            # Higher initial prices to prevent initial over-allocation
            p_cpu = params.get('initial_p_cpu', 5.0)
            p_memory = params.get('initial_p_memory', 2.0)

        except Exception as e:
            print(f"Error reading pricing config: {e}. Using default prices.")
            p_cpu, p_memory = 5.0, 2.0

        if verbose:
            print("=" * 80)
            print("STARTING STACKELBERG GAME OPTIMIZATION")
            print("=" * 80)
            print(f"Cluster Resources: CPU={self.cluster.total_cpu}, Memory={self.cluster.total_memory}")
            print(f"Platform Utility Weights: Utilization={self.alpha1}, Fairness={self.alpha2}, SLO Penalty={self.alpha3}")
            print("\nTenant Details:")
            for i, tenant in enumerate(self.tenants):
                print(f"  {tenant.name}: Budget=${tenant.budget}, Min CPU={tenant.min_cpu}, Min Memory={tenant.min_memory}, Desired Replicas={tenant.desired_replicas}, Priority={getattr(tenant, 'priority', 1.0)}")
            print("\n" + "=" * 80)

        # Initialize tracking variables
        best_platform_utility = -float('inf')
        best_allocation = None
        best_prices = (p_cpu, p_memory)
        best_details = None
        
        # ✅ Initialize fallback allocation with minimum viable resources
        fallback_allocation = self._get_fallback_allocation()
        fallback_prices = (p_cpu, p_memory)
        fallback_details = None

        history = {
            'prices': [],
            'allocations': [],
            'platform_utility': [],
            'platform_details': [],
            'tenant_utilities': [],
            'tenant_details': []
        }

        prev_allocations = None
        constraint_violation_count = 0
        all_slos_satisfied_ever = False  # Track if we ever found a solution with all SLOs satisfied

        # Main optimization loop - try to find optimal solution
        for iteration in range(max_iterations):
            if verbose:
                print(f"\n--- Iteration {iteration + 1} ---")
                print(f"Prices: CPU=${p_cpu:.3f}/core, Memory=${p_memory:.3f}/GB")

            # Tenants respond to current prices
            allocations = []
            tenant_utilities = []
            tenant_details_list = []

            for i in range(3):
                cpu_per_replica, memory_per_replica, replicas, details = self.tenant_optimize(i, p_cpu, p_memory, verbose)
                allocations.append((cpu_per_replica, memory_per_replica, replicas))
                tenant_utilities.append(details['net_utility'])
                tenant_details_list.append(details)

            # Calculate resource utilization
            util = self._calculate_resource_utilization(allocations)
            cpu_utilization = util['cpu']
            memory_utilization = util['memory']
            total_cpu = util['total_cpu']
            total_memory = util['total_memory']

            if verbose:
                print(f"Resource Usage: CPU={total_cpu:.1f}/{self.cluster.total_cpu} ({cpu_utilization:.1%}), "
                    f"Memory={total_memory:.1f}/{self.cluster.total_memory} ({memory_utilization:.1%})")

            # Check if resources exceed cluster capacity
            resource_violation = total_cpu > self.cluster.total_cpu or total_memory > self.cluster.total_memory
            
            if resource_violation:
                if verbose:
                    print("   ❌ Resource constraints violated. Attempting redistribution...")
                allocations = self._redistribute_resources(allocations, total_cpu, total_memory)
                util = self._calculate_resource_utilization(allocations)
                total_cpu = util['total_cpu']
                total_memory = util['total_memory']
                
                if verbose:
                    print(f"   After redistribution: CPU={total_cpu:.1f}/{self.cluster.total_cpu}, "
                        f"Memory={total_memory:.1f}/{self.cluster.total_memory}")

            # After redistribution, check if we're within cluster limits
            if total_cpu <= self.cluster.total_cpu and total_memory <= self.cluster.total_memory:
                constraint_violation_count = 0  # Reset counter

                platform_utility, platform_breakdown = self.platform_utility(allocations, p_cpu, p_memory)

                # ✅ Always update fallback with any valid solution
                if fallback_allocation is None:
                    fallback_allocation = allocations.copy()
                    fallback_prices = (p_cpu, p_memory)
                    fallback_details = platform_breakdown.copy()

                # Check if all SLOs are satisfied
                current_slos_satisfied = all(slo_detail['slo_met'] for slo_detail in platform_breakdown['slo_details'])
                if current_slos_satisfied:
                    all_slos_satisfied_ever = True
                    if verbose:
                        print("   🎉 ALL SLOs SATISFIED!")
                        # REMOVED: Don't return immediately, continue to find potentially better solution

                if platform_utility > best_platform_utility:
                    best_platform_utility = platform_utility
                    best_allocation = allocations.copy()
                    best_prices = (p_cpu, p_memory)
                    best_details = platform_breakdown.copy()

                    if verbose:
                        print(f"   🎉 NEW BEST SOLUTION FOUND! Platform Utility: {platform_utility:.3f}")

                history['prices'].append((p_cpu, p_memory))
                history['allocations'].append(allocations.copy())
                history['platform_utility'].append(platform_utility)
                history['platform_details'].append(platform_breakdown.copy())
                history['tenant_utilities'].append(tenant_utilities.copy())
                history['tenant_details'].append(tenant_details_list.copy())

                if verbose:
                    print("   SLO Status:")
                    for slo_detail in platform_breakdown['slo_details']:
                        status = "✅ PASS" if slo_detail['slo_met'] else "❌ FAIL"
                        print(f"     {slo_detail['tenant']}: {status}")

                # Check for convergence
                if prev_allocations is not None:
                    allocation_change = sum(
                        abs(curr[0]*curr[2] - prev[0]*prev[2]) + abs(curr[1]*curr[2] - prev[1]*prev[2])
                        for curr, prev in zip(allocations, prev_allocations)
                    )

                    if allocation_change < 0.1:  # Convergence threshold
                        if verbose:
                            print("   🔄 Converged - allocation changes below threshold")
                        break

                prev_allocations = allocations.copy()

            else:
                constraint_violation_count += 1
                if verbose:
                    print("   ❌ Resource constraints still violated after redistribution. Skipping iteration.")

                # If constraints are violated too many times, terminate early
                if constraint_violation_count >= 5:
                    if verbose:
                        print("   ⚠️ Too many constraint violations. Terminating early.")
                    break

            # Platform adjusts prices using improved method
            old_p_cpu, old_p_memory = p_cpu, p_memory
            p_cpu, p_memory = self._adjust_prices(p_cpu, p_memory, cpu_utilization, memory_utilization)

        # AT THIS POINT: Algorithm completed either by convergence or max iterations
        
        # If we found a best solution during iterations, use it
        if best_allocation is not None and best_platform_utility > -float('inf'):
            final_allocation = best_allocation
            final_prices = best_prices
            final_details = best_details
            final_utility = best_platform_utility
            final_all_slos_satisfied = all(slo_detail['slo_met'] for slo_detail in best_details['slo_details'])
            
            if verbose:
                print(f"\n✅ Using best solution found during optimization with utility: {final_utility:.3f}")
        else:
            # If no optimal solution found, select best from history using SLO-prioritized selection
            if verbose:
                print(f"\n⚠️ No optimal solution found. Using fallback strategy...")
                
            if history['allocations']:
                if verbose:
                    print(f"\n⚠️ Selecting best iteration from {len(history['allocations'])} candidates...")
                
                selected_allocation, selected_prices, selected_details, selected_index = self._select_best_iteration(history, verbose)
                
                if selected_allocation is not None:
                    final_allocation = selected_allocation
                    final_prices = selected_prices
                    final_details = selected_details
                    final_utility = history['platform_utility'][selected_index]
                    final_all_slos_satisfied = all(slo_detail['slo_met'] for slo_detail in selected_details['slo_details'])
                    
                    if verbose:
                        print(f"✅ Selected iteration {selected_index + 1} as final solution")
                else:
                    final_allocation = fallback_allocation
                    final_prices = fallback_prices
                    final_details = fallback_details
                    final_utility = -float('inf')
                    final_all_slos_satisfied = False
            else:
                final_allocation = fallback_allocation
                final_prices = fallback_prices
                final_details = fallback_details
                final_utility = -float('inf')
                final_all_slos_satisfied = False
        
        # Final fallback if everything fails
        if final_allocation is None:
            if verbose:
                print("⚠️ WARNING: No valid allocation found, using emergency minimum allocation")
            final_allocation = self._get_emergency_allocation()
            final_prices = (1.0, 0.5)
            final_details = {'emergency_mode': True, 'utilization': 0.1, 'fairness': 1.0, 'slo_violation_score': 0}
            final_utility = -1000
            final_all_slos_satisfied = False

        return {
            'allocations': final_allocation,
            'prices': final_prices,
            'platform_utility': final_utility,
            'platform_details': final_details,
            'history': history,
            'converged': len(history['platform_utility']) < max_iterations,
            'all_slos_satisfied': final_all_slos_satisfied
        }

    def _get_fallback_allocation(self):
        """Get a basic allocation using minimum resources for each tenant"""
        try:
            fallback_allocations = []
            for tenant in self.tenants:
                # Use minimum viable resources
                cpu_per_replica = max(tenant.min_cpu, 0.1)
                memory_per_replica = max(tenant.min_memory, 0.5)
                replicas = max(tenant.min_replicas, 1)  
                
                fallback_allocations.append((cpu_per_replica, memory_per_replica, replicas))
            
            # Check if fallback fits in cluster
            total_cpu = sum(alloc[0] * alloc[2] for alloc in fallback_allocations)
            total_memory = sum(alloc[1] * alloc[2] for alloc in fallback_allocations)
            
            if total_cpu <= self.cluster.total_cpu and total_memory <= self.cluster.total_memory:
                return fallback_allocations
            else:
                # Scale down proportionally if doesn't fit
                cpu_scale = self.cluster.total_cpu / max(total_cpu, 0.1)
                memory_scale = self.cluster.total_memory / max(total_memory, 0.1)
                scale = min(cpu_scale, memory_scale) * 0.8  # Use 80% to leave some buffer
                
                scaled_allocations = []
                for cpu_per_replica, memory_per_replica, replicas in fallback_allocations:
                    scaled_cpu = max(cpu_per_replica * scale, 0.1)
                    scaled_memory = max(memory_per_replica * scale, 0.5)
                    scaled_allocations.append((scaled_cpu, scaled_memory, replicas))
                
                return scaled_allocations
        except Exception as e:
            print(f"Error creating fallback allocation: {e}")
            return None

    def _get_emergency_allocation(self):
        """Get emergency minimum allocation when everything fails"""
        # Very conservative allocation: equal minimal resources for all tenants
        cpu_per_tenant = max(self.cluster.total_cpu / 6, 0.1)  # Divide by 6 to leave buffer
        memory_per_tenant = max(self.cluster.total_memory / 6, 0.5)
        
        emergency_allocations = []
        for i in range(3):  # 3 tenants
            emergency_allocations.append((cpu_per_tenant, memory_per_tenant, 1))
        
        return emergency_allocations

    def _calculate_resource_utilization(self, allocations):
        """Calculate CPU and memory utilization for given allocations"""
        total_cpu = sum(alloc[0] * alloc[2] for alloc in allocations)
        total_memory = sum(alloc[1] * alloc[2] for alloc in allocations)

        return {
            'cpu': total_cpu / self.cluster.total_cpu,
            'memory': total_memory / self.cluster.total_memory,
            'total_cpu': total_cpu,
            'total_memory': total_memory
        }

    def _adjust_prices(self, p_cpu, p_memory, util_cpu, util_memory):
        """Adjust prices based on resource utilization"""
        # Base adjustment factors
        cpu_adjustment = 0.05
        memory_adjustment = 0.05

        # More aggressive adjustment when overutilized
        if util_cpu > 0.9:
            cpu_adjustment *= (1 + (util_cpu - 0.9) * 5)  # Scale adjustment based on overutilization

        if util_memory > 0.9:
            memory_adjustment *= (1 + (util_memory - 0.9) * 5)

        # Apply adjustments
        if util_cpu > 0.7:  # If utilization is high, increase price
            p_cpu *= (1 + cpu_adjustment)
        elif util_cpu < 0.5:  # If utilization is low, decrease price
            p_cpu *= (1 - cpu_adjustment * 0.5)  # Less aggressive decrease

        if util_memory > 0.7:
            p_memory *= (1 + memory_adjustment)
        elif util_memory < 0.5:
            p_memory *= (1 - memory_adjustment * 0.5)

        # Ensure prices don't drop too low
        p_cpu = max(p_cpu, 0.5)
        p_memory = max(p_memory, 0.1)

        return p_cpu, p_memory

def run_comparison():
    """Run comparison between Stackelberg and Regular schedulers"""
    # Define check_slos function first
    def check_slos(allocations, scheduler, performance_metrics=None):
        slo_status = []
        for i, (cpu_per_replica, memory_per_replica, replicas) in enumerate(allocations):
            if performance_metrics:  # Use stored metrics if available
                metrics = performance_metrics[i]
            else:  # Otherwise calculate fresh
                metrics = scheduler.get_tenant_performance_metrics(i, cpu_per_replica, memory_per_replica, replicas)

            if i == 0:  # Web App
                status = "✅ PASS" if metrics['slo_met'] else "❌ FAIL"
                slo_status.append(f"Response time: {metrics['response_time']:.1f}ms {status}")
            elif i == 1:  # Data Processing
                status = "✅ PASS" if metrics['slo_met'] else "❌ FAIL"
                slo_status.append(f"Throughput: {metrics['throughput']:.1f} jobs/h {status}")
            else:  # ML Training
                status = "✅ PASS" if metrics['slo_met'] else "❌ FAIL"
                slo_status.append(f"Training time: {metrics['training_time']:.1f}h {status}")
        return slo_status

    # Define cluster and scheduler parameters
    cluster_params = {"total_cpu": 32, "total_memory": 128}
    scheduler_params = {
        "alpha1": 0.5, "alpha2": 0.3, "alpha3": 0.2,
        "initial_p_cpu": 5.0, "initial_p_memory": 2.0,
        "web_app_max_response_time": 52.5, "web_app_budget": 800,
        "web_app_min_cpu": 2, "web_app_min_memory": 8,
        "web_app_desired_replicas": 2, "web_app_min_replicas": 1,
        "web_app_priority": 1.0,
        "data_processing_min_throughput": 1000, "data_processing_budget": 1200,
        "data_processing_min_cpu": 1, "data_processing_min_memory": 4,
        "data_processing_desired_replicas": 2, "data_processing_min_replicas": 1,
        "data_processing_priority": 0.8,
        "ml_training_max_training_time": 8, "ml_training_budget": 1500,
        "ml_training_min_cpu": 4, "ml_training_min_memory": 16,
        "ml_training_desired_replicas": 1, "ml_training_min_replicas": 1,
        "ml_training_priority": 1.2,
        # Utility function parameters
        "cpu_norm": 5, "memory_norm": 20, "base_exponent": 0.7,
        "rt_const1": 50, "rt_const2": 500, "rt_exponent": 0.3,
        "latency_thresh": 52.5, "latency_penalty": 100,
        "tenant_b_base_coeff": 80, "tenant_b_memory_exp1": 0.6, "tenant_b_base_exp": 0.8,
        "tenant_b_throughput_coeff": 15, "tenant_b_throughput_cpu_exp": 0.8, "tenant_b_throughput_mem_exp": 0.4,
        "tenant_b_queue_penalty_thresh": 1000, "tenant_b_queue_penalty_coeff": 2,
        "tenant_c_base_coeff": 120, "tenant_c_memory_exp1": 0.5, "tenant_c_log_const": 1,
        "tenant_c_training_cpu_exp": 0.7, "tenant_c_training_mem_exp": 0.3,
        "tenant_c_time_penalty_thresh": 8, "tenant_c_time_penalty_coeff": 40
    }

    cluster = ClusterResources(cluster_params)
    stackelberg = StackelbergScheduler(cluster, scheduler_params)
    stack_results = stackelberg.stackelberg_equilibrium(max_iterations=25, verbose=True)

    tenants = ['Web-App', 'Data-Processing', 'ML-Training']

    print("\n" + "=" * 80)
    print("🎯 FINAL STACKELBERG GAME RESULTS:")
    print("=" * 80)
    
    for i, (cpu, mem, replicas) in enumerate(stack_results['allocations']):
        print(f"{tenants[i]}: CPU={cpu:.2f} cores/replica, Memory={mem:.2f} GB/replica, Replicas={replicas}")
        print(f"   Total Resources: CPU={cpu*replicas:.2f}, Memory={mem*replicas:.2f}")

    print(f"\n💰 Final Prices: CPU=${stack_results['prices'][0]:.3f}/core, Memory=${stack_results['prices'][1]:.3f}/GB")
    print(f"🏆 Platform Utility: {stack_results['platform_utility']:.3f}")
    print(f"🔄 Converged: {stack_results['converged']}")
    print(f"✅ All SLOs Satisfied: {stack_results['all_slos_satisfied']}")
    
    print(f"\n📊 Final Performance Metrics:")
    slo_status = check_slos(stack_results['allocations'], stackelberg)
    for i, status in enumerate(slo_status):
        print(f"   {tenants[i]}: {status}")

    return stack_results

if __name__ == "__main__":
    stack_results = run_comparison()