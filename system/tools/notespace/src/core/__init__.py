"""
Core Module - Document Management and Analysis Engine
"""

from .document_manager import DocumentManager, DocumentItem, DocumentStatus
from .project import Project, ProjectManager
from .sub_query import SubQuery, SubQueryManager
from .text_extractor import TextExtractor

__all__ = [
    'DocumentManager', 'DocumentItem', 'DocumentStatus',
    'Project', 'ProjectManager',
    'SubQuery', 'SubQueryManager',
    'TextExtractor'
]
