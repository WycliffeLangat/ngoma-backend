import logging
import os

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


@deconstructible
class CloudinaryMediaStorage(Storage):
    """
    Minimal Cloudinary storage backend.
    Stores the file path (e.g. 'covers/photo.jpg') in the DB field and
    converts to a full Cloudinary URL on read via url().
    This keeps the stored value well within ImageField's default max_length=100.
    """

    def _save(self, name, content):
        public_id = os.path.splitext(name)[0]
        try:
            result = cloudinary.uploader.upload(
                content,
                public_id=public_id,
                overwrite=True,
                resource_type="image",
                invalidate=True,
            )
            logger.info("Cloudinary upload OK: %s → %s", name, result.get("secure_url"))
        except Exception as exc:
            logger.error("Cloudinary upload FAILED for %s: %s", name, exc)
            raise
        return name  # store the short path, not the URL

    def url(self, name):
        if not name:
            return ""
        if str(name).startswith("http"):
            return name  # already an absolute URL (legacy local uploads)
        try:
            ext = os.path.splitext(name)[1].lstrip(".") or "jpg"
            public_id = os.path.splitext(name)[0]
            result, _ = cloudinary.utils.cloudinary_url(
                public_id, resource_type="image", format=ext, secure=True
            )
            if result:
                return result
        except Exception as exc:
            logger.error("Cloudinary url() FAILED for %s: %s", name, exc)
        # Fallback: return as a relative path so to_representation can build absolute
        return f"/media/{name}"

    def exists(self, name):
        return False  # let Cloudinary handle overwrites via overwrite=True

    def delete(self, name):
        try:
            public_id = os.path.splitext(name)[0]
            cloudinary.uploader.destroy(public_id, resource_type="image")
        except Exception:
            pass

    def _open(self, name, mode="rb"):
        raise NotImplementedError("CloudinaryMediaStorage does not support open().")

    def size(self, name):
        return 0

    def path(self, name):
        raise NotImplementedError("CloudinaryMediaStorage does not support local paths.")
