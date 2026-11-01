"""Auto-inject coaching knowledge into system prompt for specific contexts.

When the agent is working on a training plan, relevant coaching knowledge
is loaded from disk and appended to the system prompt so the LLM always
has access to evidence-based protocols without needing a tool call.
"""

from pathlib import Path
from config.hybrid_config import get_logger

logger = get_logger(__name__)

_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent / 'data' / 'coaching_knowledge'

# Topics to inject for training plan conversations (~5.7k tokens total)
_TRAINING_PLAN_TOPICS = ['periodization', 'weekly_structure', 'uphill_training']

# Cache loaded knowledge to avoid repeated disk reads
_knowledge_cache: dict[str, str] = {}


def _load_topic(topic: str) -> str:
    """Load a single knowledge topic from disk, with caching."""
    if topic in _knowledge_cache:
        return _knowledge_cache[topic]

    filepath = _KNOWLEDGE_DIR / f'{topic}.md'
    if not filepath.exists():
        logger.warning(f"Knowledge topic file not found: {filepath}")
        return ''

    content = filepath.read_text(encoding='utf-8')
    _knowledge_cache[topic] = content
    return content


def get_training_plan_knowledge() -> str:
    """Load and format coaching knowledge for training plan contexts.

    Returns a formatted string ready to append to the system prompt,
    containing periodization, weekly structure, and uphill training
    knowledge (~5.7k tokens).
    """
    sections = []
    for topic in _TRAINING_PLAN_TOPICS:
        content = _load_topic(topic)
        if content:
            sections.append(content)

    if not sections:
        return ''

    return (
        '\n\n---\n\n'
        '## Coaching Reference (auto-loaded — DO NOT call lookup_coaching_knowledge for these topics)\n'
        'The following topics are already loaded: periodization, weekly_structure, uphill_training.\n'
        'Do NOT waste a tool call looking them up — you already have them below.\n'
        'Only call lookup_coaching_knowledge for OTHER topics (nutrition, recovery, mental_toughness, etc.) '
        'if the user asks about them.\n\n'
        + '\n\n---\n\n'.join(sections)
    )
