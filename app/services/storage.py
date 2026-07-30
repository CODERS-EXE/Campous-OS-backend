from typing import Optional

from app.core.config import get_settings

settings = get_settings()


def configure_cloudinary() -> bool:
    if not all([settings.CLOUDINARY_CLOUD_NAME, settings.CLOUDINARY_API_KEY, settings.CLOUDINARY_API_SECRET]):
        return False
    import cloudinary

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    return True


async def upload_file(file_bytes: bytes, folder: str, public_id: str) -> Optional[str]:
    if not configure_cloudinary():
        return None
    import cloudinary.uploader

    result = cloudinary.uploader.upload(
        file_bytes,
        folder=f"campusos/{folder}",
        public_id=public_id,
        resource_type="auto",
    )
    return result.get("secure_url")
