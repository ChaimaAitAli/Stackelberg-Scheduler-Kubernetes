import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize
from dataclasses import dataclass
from typing import List, Tuple, Dict

@dataclass
class ClusterResources:
    def __init__(self, params: Dict[str, float]):
        self.total_cpu = params["total_cpu"]
        self.total_memory = params["total_memory"]

@dataclass
class Tenant:
    name: str
    max_response_time: float = None
    min_throughput: float = None
    max_training_time: float = None
    budget: float = 1000.0
    min_cpu: float = 1.0
    min_memory: float = 4.0
    desired_replicas: int = None
    min_replicas: int = None

class KubernetesSchedulerSimulator:
    def __init__(self, cluster: ClusterResources, params: Dict[str, float]):
        self.cluster = cluster
        self.params = params
        self.tenant_config = self._load_tenant_config()
        self.tenants = self._setup_tenants()

    def _load_tenant_config(self) -> Dict:
        params = self.params
        return {
            'web_app': {
                'max_response_time': params["web_app_max_response_time"],
                'budget': params["web_app_budget"],
                'min_cpu': params["web_app_min_cpu"],
                'min_memory': params["web_app_min_memory"],
                'desired_replicas': params["web_app_desired_replicas"],
                'min_replicas': params["web_app_min_replicas"],
            },
            'data_processing': {
                'min_throughput': params["data_processing_min_throughput"],
                'budget': params["data_processing_budget"],
                'min_cpu': params["data_processing_min_cpu"],
                'min_memory': params["data_processing_min_memory"],
                'desired_replicas': params["data_processing_desired_replicas"],
                'min_replicas': params["data_processing_min_replicas"],
            },
            'ml_training': {
                'max_training_time': params["ml_training_max_training_time"],
                'budget': params["ml_training_budget"],
                'min_cpu': params["ml_training_min_cpu"],
                'min_memory': params["ml_training_min_memory"],
                'desired_replicas': params["ml_training_desired_replicas"],
                'min_replicas': params["ml_training_min_replicas"],
            }
        }

    def _setup_tenants(self) -> List[Tenant]:
        return [
            Tenant(
                name="Web-App",
                max_response_time=self.tenant_config['web_app']['max_response_time'],
                budget=self.tenant_config['web_app']['budget'],
                min_cpu=self.tenant_config['web_app']['min_cpu'],
                min_memory=self.tenant_config['web_app']['min_memory'],
                desired_replicas=self.tenant_config['web_app']['desired_replicas'],
                min_replicas=self.tenant_config['web_app']['min_replicas'],
            ),
            Tenant(
                name="Data-Processing",
                min_throughput=self.tenant_config['data_processing']['min_throughput'],
                budget=self.tenant_config['data_processing']['budget'],
                min_cpu=self.tenant_config['data_processing']['min_cpu'],
                min_memory=self.tenant_config['data_processing']['min_memory'],
                desired_replicas=self.tenant_config['data_processing']['desired_replicas'],
                min_replicas=self.tenant_config['data_processing']['min_replicas'],
            ),
            Tenant(
                name="ML-Training",
                max_training_time=self.tenant_config['ml_training']['max_training_time'],
                budget=self.tenant_config['ml_training']['budget'],
                min_cpu=self.tenant_config['ml_training']['min_cpu'],
                min_memory=self.tenant_config['ml_training']['min_memory'],
                desired_replicas=self.tenant_config['ml_training']['desired_replicas'],
                min_replicas=self.tenant_config['ml_training']['min_replicas'],
            )
        ]
class StackelbergScheduler(KubernetesSchedulerSimulator):
    def __init__(self, cluster: ClusterResources, params: Dict[str, float]):
        self.params = params
        self.alpha1 = params["alpha1"]
        self.alpha2 = params["alpha2"]
        self.alpha3 = params["alpha3"]
        super().__init__(cluster, params)

    def tenant_a_utility(self, cpu_per_replica: float, memory_per_replica: float, replicas: int) -> float:
        params = self.params
        cpu_norm = params["cpu_norm"]
        memory_norm = params["memory_norm"]
        base_exponent = params["base_exponent"]
        rt_const1 = params["rt_const1"]
        rt_const2 = params["rt_const2"]
        rt_exponent = params["rt_exponent"]
        latency_thresh = params["latency_thresh"]
        latency_penalty = params["latency_penalty"]

        base_utility_per_replica = 200 * min(cpu_per_replica / cpu_norm, memory_per_replica / memory_norm) ** base_exponent
        response_time = rt_const1 + rt_const2 / (cpu_per_replica * memory_per_replica ** rt_exponent)
        penalty_per_replica = max(0, latency_penalty * (response_time - latency_thresh)) if response_time > latency_thresh else 0
        total_utility = (base_utility_per_replica - penalty_per_replica) * (replicas ** 0.8)
        return total_utility

    def tenant_b_utility(self, cpu_per_replica: float, memory_per_replica: float, replicas: int) -> float:
        params = self.params
        base_coeff = params["tenant_b_base_coeff"]
        memory_exp1 = params["tenant_b_memory_exp1"]
        base_exp = params["tenant_b_base_exp"]
        throughput_coeff = params["tenant_b_throughput_coeff"]
        throughput_cpu_exp = params["tenant_b_throughput_cpu_exp"]
        throughput_mem_exp = params["tenant_b_throughput_mem_exp"]
        queue_penalty_thresh = params["tenant_b_queue_penalty_thresh"]
        queue_penalty_coeff = params["tenant_b_queue_penalty_coeff"]

        base_utility_per_replica = base_coeff * np.log(1 + (cpu_per_replica * memory_per_replica ** memory_exp1) ** base_exp)
        actual_throughput_per_replica = throughput_coeff * cpu_per_replica ** throughput_cpu_exp * memory_per_replica ** throughput_mem_exp
        required_throughput_per_replica = queue_penalty_thresh / max(replicas, 1)
        penalty_per_replica = queue_penalty_coeff * (required_throughput_per_replica - actual_throughput_per_replica) if actual_throughput_per_replica < required_throughput_per_replica else 0
        total_utility = (base_utility_per_replica - penalty_per_replica) * (replicas ** 0.8)
        return total_utility

    def tenant_c_utility(self, cpu_per_replica: float, memory_per_replica: float, replicas: int) -> float:
        params = self.params
        base_coeff = params["tenant_c_base_coeff"]
        memory_exp1 = params["tenant_c_memory_exp1"]
        log_const = params["tenant_c_log_const"]
        training_cpu_exp = params["tenant_c_training_cpu_exp"]
        training_mem_exp = params["tenant_c_training_mem_exp"]
        time_penalty_thresh = params["tenant_c_time_penalty_thresh"]
        time_penalty_coeff = params["tenant_c_time_penalty_coeff"]

        base_utility_per_replica = base_coeff * np.log(log_const + cpu_per_replica ** 0.9 * memory_per_replica ** memory_exp1)
        training_time = 20 / (cpu_per_replica ** training_cpu_exp * memory_per_replica ** training_mem_exp)
        penalty_per_replica = max(0, time_penalty_coeff * (training_time - time_penalty_thresh)) if training_time > time_penalty_thresh else 0
        total_utility = (base_utility_per_replica - penalty_per_replica) * (replicas ** 0.9)
        return total_utility

    def get_tenant_performance_metrics(self, tenant_idx: int, cpu_per_replica: float, memory_per_replica: float, replicas: int) -> Dict:
        def is_close(a, b, rel_tol=1e-5, abs_tol=1e-5):
            return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

        params = self.params
        metrics = {}
        total_cpu = cpu_per_replica * replicas
        total_memory = memory_per_replica * replicas

        if tenant_idx == 0:
            rt_const1 = params["rt_const1"]
            rt_const2 = params["rt_const2"]
            rt_exponent = params["rt_exponent"]
            latency_thresh = params["latency_thresh"]

            response_time = rt_const1 + rt_const2 / (cpu_per_replica * memory_per_replica ** rt_exponent)
            metrics['response_time'] = response_time
            metrics['slo_met'] = response_time <= latency_thresh or is_close(response_time, latency_thresh)
            metrics['slo_violation_severity'] = max(0, (response_time - latency_thresh) / latency_thresh) if response_time > latency_thresh else 0

        elif tenant_idx == 1:
            throughput_coeff = params["tenant_b_throughput_coeff"]
            throughput_cpu_exp = params["tenant_b_throughput_cpu_exp"]
            throughput_mem_exp = params["tenant_b_throughput_mem_exp"]
            queue_penalty_thresh = params["tenant_b_queue_penalty_thresh"]

            throughput = throughput_coeff * cpu_per_replica ** throughput_cpu_exp * memory_per_replica ** throughput_mem_exp * replicas
            metrics['throughput'] = throughput
            metrics['slo_met'] = throughput >= queue_penalty_thresh
            metrics['slo_violation_severity'] = max(0, (queue_penalty_thresh - throughput) / queue_penalty_thresh) if throughput < queue_penalty_thresh else 0

        else:
            training_cpu_exp = params["tenant_c_training_cpu_exp"]
            training_mem_exp = params["tenant_c_training_mem_exp"]
            time_penalty_thresh = params["tenant_c_time_penalty_thresh"]

            training_time = 20 / (cpu_per_replica ** training_cpu_exp * memory_per_replica ** training_mem_exp)
            metrics['training_time'] = training_time
            metrics['slo_met'] = training_time <= time_penalty_thresh
            metrics['slo_violation_severity'] = max(0, (training_time - time_penalty_thresh) / time_penalty_thresh) if training_time > time_penalty_thresh else 0

        metrics['replicas'] = replicas
        metrics['total_cpu'] = total_cpu
        metrics['total_memory'] = total_memory
        return metrics

    def tenant_optimize(self, tenant_idx: int, p_cpu: float, p_memory: float, verbose: bool = False) -> Tuple[float, float, int, Dict]:
        tenant = self.tenants[tenant_idx]

        def objective(x):
            cpu_per_replica, memory_per_replica, replicas = x
            total_cpu = cpu_per_replica * replicas
            total_memory = memory_per_replica * replicas

            if tenant_idx == 0:
                utility = self.tenant_a_utility(cpu_per_replica, memory_per_replica, replicas)
            elif tenant_idx == 1:
                utility = self.tenant_b_utility(cpu_per_replica, memory_per_replica, replicas)
            else:
                utility = self.tenant_c_utility(cpu_per_replica, memory_per_replica, replicas)

            total_cost = p_cpu * total_cpu + p_memory * total_memory
            return -(utility - total_cost)

        constraints = [
            {'type': 'ineq', 'fun': lambda x: x[0] - tenant.min_cpu},
            {'type': 'ineq', 'fun': lambda x: x[1] - tenant.min_memory},
            {'type': 'ineq', 'fun': lambda x: x[2] - tenant.min_replicas},
            {'type': 'ineq', 'fun': lambda x: tenant.budget - (p_cpu * x[0] * x[2] + p_memory * x[1] * x[2])}
        ]

        bounds = [
            (tenant.min_cpu, self.cluster.total_cpu),
            (tenant.min_memory, self.cluster.total_memory),
            (tenant.min_replicas, tenant.desired_replicas)
        ]

        x0 = [tenant.min_cpu * 2, tenant.min_memory * 2, tenant.min_replicas]
        result = minimize(objective, x0, method='SLSQP', bounds=bounds, constraints=constraints)

        if result.success:
            cpu, mem, reps = result.x[0], result.x[1], int(round(result.x[2]))
        else:
            cpu, mem, reps = tenant.min_cpu, tenant.min_memory, tenant.min_replicas

        metrics = self.get_tenant_performance_metrics(tenant_idx, cpu, mem, reps)
        cost = p_cpu * cpu * reps + p_memory * mem * reps
        utility = self.tenant_a_utility(cpu, mem, reps) if tenant_idx == 0 else \
                  self.tenant_b_utility(cpu, mem, reps) if tenant_idx == 1 else \
                  self.tenant_c_utility(cpu, mem, reps)

        return cpu, mem, reps, {
            'gross_utility': utility,
            'total_cost': cost,
            'net_utility': utility - cost,
            'budget_used_pct': (cost / tenant.budget) * 100,
            'performance_metrics': metrics,
            'optimization_success': result.success
        }
    def jains_fairness_index(self, values):
        values = np.array(values)
        values = np.maximum(values, 0.01)
        numerator = np.sum(values) ** 2
        denominator = len(values) * np.sum(values ** 2)
        return numerator / denominator if denominator > 0 else 1.0

    def platform_utility(self, allocations: List[Tuple[float, float, int]], p_cpu: float, p_memory: float) -> Tuple[float, Dict]:
        total_cpu_used = sum(cpu * r for cpu, _, r in allocations)
        total_memory_used = sum(mem * r for _, mem, r in allocations)

        cpu_util = total_cpu_used / self.cluster.total_cpu
        mem_util = total_memory_used / self.cluster.total_memory
        utilization = (cpu_util + mem_util) / 2

        cpu_allocs = [cpu * r for cpu, _, r in allocations]
        mem_allocs = [mem * r for _, mem, r in allocations]
        fairness = (self.jains_fairness_index(cpu_allocs) + self.jains_fairness_index(mem_allocs)) / 2

        slo_score = 0
        slo_details = []
        for i, (cpu, mem, r) in enumerate(allocations):
            metrics = self.get_tenant_performance_metrics(i, cpu, mem, r)
            slo_score += metrics['slo_violation_severity']
            slo_details.append({
                'tenant': self.tenants[i].name,
                'slo_met': metrics['slo_met'],
                'violation_severity': metrics['slo_violation_severity'],
                'metrics': metrics
            })

        platform_util = (self.alpha1 * utilization +
                         self.alpha2 * fairness -
                         self.alpha3 * slo_score / 3)

        return platform_util, {
            'utilization': utilization,
            'cpu_utilization': cpu_util,
            'memory_utilization': mem_util,
            'fairness': fairness,
            'slo_violation_score': slo_score,
            'slo_details': slo_details,
            'total_cpu_used': total_cpu_used,
            'total_memory_used': total_memory_used,
            'revenue': p_cpu * total_cpu_used + p_memory * total_memory_used
        }

    def stackelberg_equilibrium(self, max_iterations: int = 25, verbose: bool = True) -> Dict:
        params = self.params
        p_cpu = params["initial_p_cpu"]
        p_memory = params["initial_p_memory"]

        best_util = -float('inf')
        best_alloc = None
        best_prices = (p_cpu, p_memory)
        best_details = None

        for _ in range(max_iterations):
            allocations = []
            for i in range(3):
                cpu, mem, reps, _ = self.tenant_optimize(i, p_cpu, p_memory, verbose)
                allocations.append((cpu, mem, reps))

            total_cpu = sum(cpu * r for cpu, _, r in allocations)
            total_mem = sum(mem * r for _, mem, r in allocations)

            if total_cpu > self.cluster.total_cpu or total_mem > self.cluster.total_memory:
                p_cpu *= 1.1
                p_memory *= 1.1
                continue

            util, details = self.platform_utility(allocations, p_cpu, p_memory)
            if util > best_util:
                best_util = util
                best_alloc = allocations
                best_prices = (p_cpu, p_memory)
                best_details = details

            if util > 0.99:
                break

            # Adjust prices dynamically
            cpu_util = details['cpu_utilization']
            mem_util = details['memory_utilization']

            if cpu_util > 0.7:
                p_cpu *= 1.05
            elif cpu_util < 0.5:
                p_cpu *= 0.95

            if mem_util > 0.7:
                p_memory *= 1.05
            elif mem_util < 0.5:
                p_memory *= 0.95

            p_cpu = max(p_cpu, 0.1)
            p_memory = max(p_memory, 0.05)

        return {
            "allocations": best_alloc,
            "prices": best_prices,
            "platform_utility": best_util,
            "platform_details": best_details
        }
