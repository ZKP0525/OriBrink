import uvicorn

from shared.config import settings


def main() -> None:
    uvicorn.run(
        "services.api_service.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
