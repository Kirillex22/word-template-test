import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

class VariableType(str, Enum):
    TEXT = "text"
    CHECKBOX = "checkbox"
    CHECKBOX_EXISTING = "checkbox_existing"
    DATE = "date"

@dataclass
class VariableMetadata:
    display_name: str = ""
    description: str = ""
    required: bool = False
    validation_regex: Optional[str] = None
    default_value: Any = ""
    ui_order: int = 0
    category: str = "general"

@dataclass
class TemplateVariable:
    """Переменная в контексте шаблона — содержит ссылку на переменную коллекции и метаданные расположения"""
    name: str
    collection_var_name: Optional[str] = None
    type: VariableType = VariableType.TEXT
    comment_ids: List[str] = None
    contexts: List[str] = None
    occurrences: int = 1
    locations: List[dict] = None

    def __post_init__(self):
        if self.comment_ids is None:
            self.comment_ids = []
        if self.contexts is None:
            self.contexts = []
        if self.locations is None:
            self.locations = []

    def to_dict(self):
        data = {
            'name': self.name,
            'collection_var_name': self.collection_var_name,
            'type': self.type.value,
            'comment_ids': list(self.comment_ids),
            'contexts': list(self.contexts),
            'occurrences': self.occurrences,
            'locations': list(self.locations),
            'comment_id': self.comment_ids[0] if self.comment_ids else "",
            'context': self.contexts[0] if self.contexts else ""
        }
        return data


@dataclass
class CollectionVariable:
    name: str
    type: VariableType = VariableType.TEXT
    metadata: Optional[VariableMetadata] = None
    value: Any = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self):
        data = asdict(self)
        data['type'] = self.type.value
        if self.metadata:
            data['metadata'] = asdict(self.metadata)
        return data

@dataclass
class DocumentTemplate:
    id: str
    name: str
    original_filename: str
    collection_id: str
    variables: Dict[str, TemplateVariable]
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    file_hash: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self):
        data = asdict(self)
        data['variables'] = {k: v.to_dict() for k, v in self.variables.items()}
        return data

@dataclass
class Collection:
    id: str
    name: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    templates: List[str] = None
    variables: Dict[str, CollectionVariable] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.templates is None:
            self.templates = []
        if self.variables is None:
            self.variables = {}

    def to_dict(self):
        return asdict(self)
