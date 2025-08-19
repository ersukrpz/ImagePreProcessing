from pydantic import BaseModel, Field

class Camera(BaseModel):
    id: str = Field(..., min_length=1)
    ip: str = Field(..., min_length=8)
