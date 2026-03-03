# src/features/procurement_assistant/models/conversation_model.py
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field

class ConversationState(str, Enum):
    INITIAL = "initial"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    MODIFYING = "modifying"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"

class UserIntent(str, Enum):
    CONFIRM = "confirm"
    ADD = "add"
    REMOVE = "remove"
    MODIFY = "modify"
    CANCEL = "cancel"
    UNKNOWN = "unknown"

@dataclass
class ConversationContext:
    """Stores the current conversation state"""
    session_id: str
    state: ConversationState = ConversationState.INITIAL
    current_request: Optional[Dict[str, Any]] = None
    previous_requests: List[Dict[str, Any]] = field(default_factory=list)
    modification_history: List[Dict[str, Any]] = field(default_factory=list)
    last_message: str = ""
    last_intent: UserIntent = UserIntent.UNKNOWN
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Ensure lists are initialized"""
        if self.previous_requests is None:
            self.previous_requests = []
        if self.modification_history is None:
            self.modification_history = []
    
    def update(self, **kwargs):
        """Update context and timestamp"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.now()
    
    def add_to_history(self, request_data: Dict[str, Any]):
        """Add request to history before modification"""
        if request_data:
            # Make a deep copy to avoid reference issues
            import copy
            self.previous_requests.append(copy.deepcopy(request_data))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "current_request": self.current_request,
            "previous_requests_count": len(self.previous_requests),
            "modification_history_count": len(self.modification_history),
            "last_message": self.last_message,
            "last_intent": self.last_intent.value if self.last_intent else "unknown",
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }