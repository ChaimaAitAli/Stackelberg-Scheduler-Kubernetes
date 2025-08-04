# stackelberg_core.py
from typing import Dict, Optional
import math
from stackelbergRefactored import StackelbergScheduler, ClusterResources

def sanitize_float(value, default=0.0, min_val=None, max_val=None):
    """Sanitize float values to ensure JSON compliance"""
    try:
        if value is None or math.isnan(value) or math.isinf(value):
            return default
        
        value = float(value)
        
        if min_val is not None:
            value = max(value, min_val)
        if max_val is not None:
            value = min(value, max_val)
            
        return value
    except (ValueError, TypeError, OverflowError):
        return default

def run_stackelberg(total_cpu: float, total_memory: float, params: Optional[Dict[str, float]] = None):
    try:
        params = params or {}
        params["total_cpu"] = total_cpu
        params["total_memory"] = total_memory

        cluster = ClusterResources(params)
        scheduler = StackelbergScheduler(cluster, params)
        result = scheduler.stackelberg_equilibrium(verbose=False)

        # ✅ Validate that allocations exist and are not None
        allocations = result.get("allocations")
        if allocations is None:
            raise ValueError("No allocations returned from stackelberg algorithm")

        # ✅ Validate allocations structure
        if not isinstance(allocations, list) or len(allocations) != 3:
            raise ValueError(f"Invalid allocations format: expected list of 3 tuples, got {type(allocations)} with length {len(allocations) if isinstance(allocations, list) else 'N/A'}")

        # ✅ Build response with validation
        response_allocations = []
        for i, allocation in enumerate(allocations):
            if not isinstance(allocation, tuple) or len(allocation) != 3:
                raise ValueError(f"Invalid allocation format for tenant {i}: expected tuple of 3 values, got {type(allocation)}")
            
            cpu, mem, replicas = allocation
            
            # ✅ Sanitize values to ensure JSON compliance
            cpu = sanitize_float(cpu, default=0.1, min_val=0.1, max_val=total_cpu)
            mem = sanitize_float(mem, default=0.5, min_val=0.5, max_val=total_memory)
            replicas = max(int(sanitize_float(replicas, default=1, min_val=1)), 1)
            
            response_allocations.append({
                "tenant": scheduler.tenants[i].name,
                "cpu_per_replica": round(cpu, 2),
                "memory_per_replica": round(mem, 2),
                "replicas": replicas
            })

        # ✅ Validate and sanitize prices
        prices = result.get("prices", (1.0, 0.5))
        if not isinstance(prices, tuple) or len(prices) != 2:
            prices = (1.0, 0.5)  # Fallback prices

        cpu_price = sanitize_float(prices[0], default=1.0, min_val=0.1, max_val=1000.0)
        memory_price = sanitize_float(prices[1], default=0.5, min_val=0.1, max_val=1000.0)

        # ✅ Sanitize platform utility
        platform_utility = sanitize_float(result.get("platform_utility"), default=-1000.0, min_val=-10000.0, max_val=10000.0)

        return {
            "allocations": response_allocations,
            "prices": {
                "cpu": round(cpu_price, 3),
                "memory": round(memory_price, 3)
            },
            "platform_utility": round(platform_utility, 2),
            "converged": bool(result.get("converged", False))
        }

    except Exception as e:
        print(f"Error in run_stackelberg: {e}")
        # ✅ Return emergency fallback response
        return get_emergency_response(total_cpu, total_memory)

def get_emergency_response(total_cpu: float, total_memory: float):
    """Return a safe emergency response when everything fails"""
    # Conservative allocation: divide resources equally among 3 tenants with buffer
    cpu_per_tenant = max(total_cpu / 6, 0.1)  # Divide by 6 to leave buffer
    memory_per_tenant = max(total_memory / 6, 0.5)
    
    return {
        "allocations": [
            {
                "tenant": "Web-App",
                "cpu_per_replica": round(cpu_per_tenant, 2),
                "memory_per_replica": round(memory_per_tenant, 2),
                "replicas": 1
            },
            {
                "tenant": "Data-Processing", 
                "cpu_per_replica": round(cpu_per_tenant, 2),
                "memory_per_replica": round(memory_per_tenant, 2),
                "replicas": 1
            },
            {
                "tenant": "ML-Training",
                "cpu_per_replica": round(cpu_per_tenant, 2), 
                "memory_per_replica": round(memory_per_tenant, 2),
                "replicas": 1
            }
        ],
        "prices": {
            "cpu": 1.0,
            "memory": 0.5
        },
        "platform_utility": -1000.0,  # Indicates emergency mode
        "converged": False
    }

# stackelberg_sidecar.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from stackelberg_core import run_stackelberg
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

class InputModel(BaseModel):
    total_cpu: float
    total_memory: float
    params: Optional[Dict[str, float]] = None

@app.post("/stackelberg/allocate")
def allocate(data: InputModel):
    try:
        # ✅ Validate input
        if data.total_cpu <= 0 or data.total_memory <= 0:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid cluster resources: CPU={data.total_cpu}, Memory={data.total_memory}"
            )
        
        logger.info(f"Processing allocation request: CPU={data.total_cpu}, Memory={data.total_memory}")
        
        result = run_stackelberg(data.total_cpu, data.total_memory, data.params)
        
        # ✅ Validate result before returning
        if not result or "allocations" not in result:
            raise HTTPException(status_code=500, detail="Invalid response from Stackelberg algorithm")
        
        logger.info("Successfully processed allocation request")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in allocate endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/health") 
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)