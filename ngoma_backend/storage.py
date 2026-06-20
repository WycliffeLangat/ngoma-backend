import os
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class CloudinaryMediaStorage(Storage):
    """
    Minimal Cloudinary storage backend.
    Stores the file path (e.g. 'covers/photo.jpg') in the DB field and
    converts to a full Cloudinary URL on read via url().
    This keeps the stored value well within ImageField's default max_length=100.
    """

    def _save(self, name, content):
        # Strip extension to use as Cloudinary public_id (e.g. 'covers/photo')
        public_id = os.path.splitext(name)[0]
        cloudinary.uploader.upload(
            content,
            public_id=public_id,
            overwrite=True,
            resource_type="image",
            invalidate=True,
        )
        return name  # store the short path, not the URL

    def url(self, name):
        if not name:
            return ""
        if str(name).startswith("http"):
            return name  # already an absolute URL (legacy local uploads)
        ext = os.path.splitext(name)[1].lstrip(".") or "jpg"
        public_id = os.path.splitext(name)[0]
        result, _ = cloudinary.utils.cloudinary_url(
            public_id, resource_type="image", format=ext, secure=True
        )
        return result

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
