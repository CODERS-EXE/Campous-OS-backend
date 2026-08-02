from app.routers.ai import router
from app.services.ai import AiService
print("AI imports OK")
print(f"Routes: {[r.path for r in router.routes]}")
methods = [m for m in dir(AiService) if not m.startswith("__")]
print(f"AiService methods: {methods}")
