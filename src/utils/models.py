from pydantic import BaseModel
from typing import List, Dict

# Projects payload
class projectModel(BaseModel):
    id: str
    description: str
    language: str

# Test request payload
class testIngestRequest(BaseModel):
    project_id: str
    text_input: str
    ai_mode: bool = False