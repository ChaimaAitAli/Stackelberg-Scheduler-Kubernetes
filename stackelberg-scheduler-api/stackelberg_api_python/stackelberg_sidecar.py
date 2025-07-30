from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Optional
from stackelberg_core import run_stackelberg

app = FastAPI()

class InputModel(BaseModel):
    total_cpu: float
    total_memory: float
    params: Optional[Dict[str, float]] = None

@app.post("/stackelberg/allocate")
def allocate(data: InputModel):
    return run_stackelberg(data.total_cpu, data.total_memory, data.params)
