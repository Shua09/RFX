# src/features/procurement_assistant/models/request_model.py
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum

class PriorityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium" 
    HIGH = "high"
    URGENT = "urgent"

class RequestStatus(str, Enum):
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    MODIFYING = "modifying"
    FINALIZED = "finalized"
    CANCELLED = "cancelled"

@dataclass
class RequestItem:
    """Individual item in a procurement request"""
    category: str
    brand: str
    quantity: int
    model: Optional[str] = None
    specifications: Optional[Dict[str, Any]] = None
    
    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}

@dataclass
class ProcurementRequest:
    """Complete procurement request structure"""
    items: List[RequestItem]
    budget_total: Optional[float] = None
    budget_per_unit: Optional[float] = None
    currency: str = "USD"
    delivery_location: Optional[str] = None
    delivery_date: Optional[str] = None
    priority: PriorityLevel = PriorityLevel.MEDIUM
    payment_terms: Optional[str] = None
    special_instructions: Optional[str] = None
    status: RequestStatus = RequestStatus.PENDING_CONFIRMATION
    session_id: Optional[str] = None
    created_at: Optional[str] = None
    
    def to_dict(self):
        result = {
            "items": [item.to_dict() for item in self.items],
            "budget_total": self.budget_total,
            "budget_per_unit": self.budget_per_unit,
            "currency": self.currency,
            "delivery_location": self.delivery_location,
            "delivery_date": self.delivery_date,
            "priority": self.priority.value,
            "payment_terms": self.payment_terms,
            "special_instructions": self.special_instructions,
            "status": self.status.value,
            "session_id": self.session_id,
            "created_at": self.created_at or datetime.now().isoformat()
        }
        # Remove None values
        return {k: v for k, v in result.items() if v is not None}