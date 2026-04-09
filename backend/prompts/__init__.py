"""
Central prompts package — re-exports all prompt strings used across the pipeline.

Import directly from the sub-modules for clarity, or from here for convenience:

    from prompts.agent import ORCHESTRATOR_SYSTEM_PROMPT
    from prompts.context import DISCOVERY_EXTRACTION_PROMPT
    from prompts.bpmn import BPMN_GENERATION_PROMPT
    from prompts.dataflow import DATAFLOW_GENERATION_PROMPT
    from prompts.srs import SRS_EXTRACTION_PROMPT
"""

from .agent import (
    DISCOVERY_SYSTEM_PROMPT,
    FINALIZER_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    RESEARCH_SYSTEM_PROMPT,
)
from .bpmn import BPMN_GENERATION_PROMPT, COMPLETENESS_PROMPT
from .context import DISCOVERY_EXTRACTION_PROMPT, RS_EXTRACTION_PROMPT
from .dataflow import DATAFLOW_COMPLETENESS_PROMPT, DATAFLOW_GENERATION_PROMPT
from .srs import SRS_EXTRACTION_PROMPT

__all__ = [
    # Agent system prompts
    "ORCHESTRATOR_SYSTEM_PROMPT",
    "RESEARCH_SYSTEM_PROMPT",
    "DISCOVERY_SYSTEM_PROMPT",
    "FINALIZER_SYSTEM_PROMPT",
    # Context / extraction prompts
    "DISCOVERY_EXTRACTION_PROMPT",
    "RS_EXTRACTION_PROMPT",
    # Diagram prompts
    "COMPLETENESS_PROMPT",
    "BPMN_GENERATION_PROMPT",
    "DATAFLOW_COMPLETENESS_PROMPT",
    "DATAFLOW_GENERATION_PROMPT",
    # SRS compilation prompt
    "SRS_EXTRACTION_PROMPT",
]
