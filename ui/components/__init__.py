"""
UI组件包 - 精简版
提供核心必要的纯组件，不直接操作session_state
"""

from .segmentation_view import SegmentationView
from .language_selection_view import LanguageSelectionView
from .audio_confirmation_view import AudioConfirmationView
from .completion_view import CompletionView
from .project_management_view import ProjectManagementView

__all__ = [
    'SegmentationView',
    'LanguageSelectionView', 
    'AudioConfirmationView',
    'CompletionView',
    'ProjectManagementView'
] 