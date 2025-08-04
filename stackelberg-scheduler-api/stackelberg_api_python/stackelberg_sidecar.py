from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from stackelberg_core import run_stackelberg
import logging

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
        if data.total_cpu <= 0 or data.total_memory <= 0:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid cluster resources: CPU={data.total_cpu}, Memory={data.total_memory}"
            )
        
        logger.info(f"Processing allocation request: CPU={data.total_cpu}, Memory={data.total_memory}")
        
        result = run_stackelberg(data.total_cpu, data.total_memory, data.params)
        
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