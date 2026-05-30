import os

HARNESS_API_KEY = os.getenv("HARNESS_API_KEY", "")
SIRI_API_KEY = os.getenv("SIRI_API_KEY", "")

SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://searxng:8080")
CRAWL4AI_BASE_URL = os.getenv("CRAWL4AI_BASE_URL", "http://crawl4ai:11235")

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://litellm:4000")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
HARNESS_MODEL = os.getenv("HARNESS_MODEL", "gemma-moe")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

MATRIX_IP = os.getenv("MATRIX_IP","192.168.4.55")
COMFY_PORT = os.getenv("COMFY_PORT","8188")
COMFY_BASE_URL = os.getenv(
	"COMFY_BASE_URL",
	f"http://{MATRIX_IP}:{COMFY_PORT}" if MATRIX_IP else "http://matrix.local:8188",
)
MEDIA_OUTPUT_DIR = os.getenv("MEDIA_OUTPUT_DIR", "/data/media")
MEDIA_PUBLIC_BASE_URL = os.getenv("MEDIA_PUBLIC_BASE_URL", "/media/files")
