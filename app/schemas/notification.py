from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class NotificationSchema(BaseModel):
    id: uuid.UUID
    type: str
    content: str
    read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
