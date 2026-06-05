import os

HARNESS_API_KEY = os.getenv("HARNESS_API_KEY", "")
SIRI_API_KEY = os.getenv("SIRI_API_KEY", "")

SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://searxng:8080")
CRAWL4AI_BASE_URL = os.getenv("CRAWL4AI_BASE_URL", "http://crawl4ai:11235")

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://litellm:4000")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
HARNESS_MODEL = os.getenv("HARNESS_MODEL", "gemma-moe")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

MATRIX_IP = os.getenv("MATRIX_IP", "192.168.4.55")
COMFY_PORT = os.getenv("COMFY_PORT", "8188")
COMFY_BASE_URL = os.getenv(
	"COMFY_BASE_URL",
	f"http://{MATRIX_IP}:{COMFY_PORT}" if MATRIX_IP else "http://matrix.local:8188",
)

# Workspace directory for local file tools (container mount point)
WORKSPACE = os.environ.get("WORKSPACE", "/home/chuck/workspace")

# Media storage base directory (container mount point). All generated media
# (images, PDFs, etc.) live under this tree and are served via /media/files/.
MEDIA_OUTPUT_DIR = os.getenv("MEDIA_OUTPUT_DIR", "/data/media")

# Base URLs for serving generated media
# INTERNAL_BASE_URL: used by internal API responses (e.g. thor.local:8090)
# PUBLIC_BASE_URL: used only by Siri-facing responses (e.g. https://siri.choukalos.com)
INTERNAL_BASE_URL = os.getenv("INTERNAL_BASE_URL", "http://thor.local:8090")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://siri.choukalos.com")
