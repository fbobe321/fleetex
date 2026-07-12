"""Constants ported from Overleaf's chat service (MessageHttpController / ThreadManager)."""

DEFAULT_MESSAGE_LIMIT = 50
MAX_MESSAGE_LENGTH = 10 * 1024  # 10240 bytes; JS uses content.length (UTF-16 units)
GLOBAL_THREAD = "GLOBAL"  # sentinel for the project's global (no thread_id) room
