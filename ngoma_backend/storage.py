import logging
import os
import base64
import io
import json
import mimetypes

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


def _parse_csv(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _drive_file_id(name):
    raw = str(name or "")
    if raw.startswith("gdrive:"):
        return raw.split(":", 2)[1]
    if raw.startswith("gdrive/"):
        return raw.split("/", 2)[1]
    return ""


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


@deconstructible
class GoogleDriveMediaStorage(Storage):
    """
    Google Drive-backed Django storage for CMS media, uploads, and backups.

    The database stores a compact value like "gdrive:<file_id>". The folder IDs
    and service-account credentials are supplied through environment variables,
    so no Google secrets are committed to the repository.
    """

    marker = "gdrive:"
    scopes = ("https://www.googleapis.com/auth/drive",)

    def __init__(
        self,
        folder_id=None,
        mirror_folder_ids=None,
        public_read=None,
        public_prefixes=None,
        url_template=None,
    ):
        self.folder_id = folder_id or getattr(settings, "GOOGLE_DRIVE_STORAGE_FOLDER_ID", "")
        self.mirror_folder_ids = (
            mirror_folder_ids
            if mirror_folder_ids is not None
            else getattr(settings, "GOOGLE_DRIVE_MIRROR_FOLDER_IDS", [])
        )
        if isinstance(self.mirror_folder_ids, str):
            self.mirror_folder_ids = _parse_csv(self.mirror_folder_ids)
        else:
            self.mirror_folder_ids = [item for item in self.mirror_folder_ids if item]
        self.public_read = (
            public_read
            if public_read is not None
            else getattr(settings, "GOOGLE_DRIVE_PUBLIC_READ", True)
        )
        self.public_prefixes = (
            public_prefixes
            if public_prefixes is not None
            else getattr(settings, "GOOGLE_DRIVE_PUBLIC_PREFIXES", [])
        )
        if isinstance(self.public_prefixes, str):
            self.public_prefixes = _parse_csv(self.public_prefixes)
        else:
            self.public_prefixes = [item for item in self.public_prefixes if item]
        self.url_template = (
            url_template
            or getattr(
                settings,
                "GOOGLE_DRIVE_URL_TEMPLATE",
                "https://drive.google.com/uc?export=view&id={file_id}",
            )
        )
        self._service = None

    def _credentials_info(self):
        raw_json = getattr(settings, "GOOGLE_DRIVE_CREDENTIALS_JSON", "")
        raw_b64 = getattr(settings, "GOOGLE_DRIVE_CREDENTIALS_B64", "")
        credentials_file = getattr(settings, "GOOGLE_DRIVE_CREDENTIALS_FILE", "")

        if raw_b64:
            raw_json = base64.b64decode(raw_b64).decode("utf-8")

        if raw_json:
            try:
                return json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise ImproperlyConfigured("GOOGLE_DRIVE_CREDENTIALS_JSON is not valid JSON.") from exc

        if credentials_file:
            with open(credentials_file, "r", encoding="utf-8") as handle:
                return json.load(handle)

        raise ImproperlyConfigured(
            "Google Drive storage requires GOOGLE_DRIVE_CREDENTIALS_JSON, "
            "GOOGLE_DRIVE_CREDENTIALS_B64, or GOOGLE_DRIVE_CREDENTIALS_FILE."
        )

    def _drive(self):
        if self._service is None:
            if not self.folder_id:
                raise ImproperlyConfigured("Google Drive storage requires GOOGLE_DRIVE_STORAGE_FOLDER_ID.")
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            credentials = service_account.Credentials.from_service_account_info(
                self._credentials_info(),
                scopes=list(self.scopes),
            )
            self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return self._service

    def _escape_query_value(self, value):
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    def _folder_for_name(self, root_folder_id, name):
        parts = [part for part in str(name or "").replace("\\", "/").split("/")[:-1] if part]
        current = root_folder_id
        for part in parts:
            current = self._ensure_child_folder(current, part)
        return current

    def _ensure_child_folder(self, parent_id, name):
        escaped = self._escape_query_value(name)
        query = (
            f"'{parent_id}' in parents and name = '{escaped}' and "
            "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        response = self._drive().files().list(
            q=query,
            spaces="drive",
            fields="files(id,name)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = response.get("files", [])
        if files:
            return files[0]["id"]

        result = self._drive().files().create(
            body={
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()
        return result["id"]

    def _should_share_publicly(self, name):
        if not self.public_read:
            return False
        normalized = str(name or "").replace("\\", "/")
        if "*" in self.public_prefixes:
            return True
        return any(normalized.startswith(prefix) for prefix in self.public_prefixes)

    def _share_publicly(self, file_id, name):
        if not self._should_share_publicly(name):
            return
        try:
            self._drive().permissions().create(
                fileId=file_id,
                body={"role": "reader", "type": "anyone"},
                fields="id",
                supportsAllDrives=True,
            ).execute()
        except Exception as exc:
            logger.warning("Google Drive public sharing failed for %s: %s", file_id, exc)

    def _upload_to_folder(self, root_folder_id, name, payload):
        from googleapiclient.http import MediaIoBaseUpload

        folder_id = self._folder_for_name(root_folder_id, name)
        filename = str(name or "upload").replace("\\", "/").rsplit("/", 1)[-1] or "upload"
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        stream = io.BytesIO(payload)
        media = MediaIoBaseUpload(stream, mimetype=mime_type, resumable=False)
        result = self._drive().files().create(
            body={
                "name": filename,
                "parents": [folder_id],
                "appProperties": {"ngoma_path": str(name or "")},
            },
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        file_id = result["id"]
        self._share_publicly(file_id, name)
        return file_id

    def _save(self, name, content):
        if hasattr(content, "seek"):
            content.seek(0)
        payload = content.read()
        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        primary_file_id = self._upload_to_folder(self.folder_id, name, payload)
        for mirror_folder_id in self.mirror_folder_ids:
            try:
                self._upload_to_folder(mirror_folder_id, name, payload)
            except Exception as exc:
                logger.error("Google Drive mirror upload FAILED for %s: %s", name, exc)
                raise

        logger.info("Google Drive upload OK: %s -> %s", name, primary_file_id)
        return f"{self.marker}{primary_file_id}"

    def url(self, name):
        file_id = _drive_file_id(name)
        if not file_id:
            return f"/media/{name}" if name else ""
        return self.url_template.format(file_id=file_id)

    def exists(self, name):
        return False

    def delete(self, name):
        file_id = _drive_file_id(name)
        if not file_id:
            return
        try:
            self._drive().files().delete(fileId=file_id, supportsAllDrives=True).execute()
        except Exception as exc:
            logger.warning("Google Drive delete failed for %s: %s", file_id, exc)

    def _open(self, name, mode="rb"):
        file_id = _drive_file_id(name)
        if not file_id:
            raise FileNotFoundError(name)
        from googleapiclient.http import MediaIoBaseDownload

        output = io.BytesIO()
        request = self._drive().files().get_media(fileId=file_id, supportsAllDrives=True)
        downloader = MediaIoBaseDownload(output, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        output.seek(0)
        return ContentFile(output.getvalue(), name=str(name))

    def size(self, name):
        file_id = _drive_file_id(name)
        if not file_id:
            return 0
        try:
            metadata = self._drive().files().get(
                fileId=file_id,
                fields="size",
                supportsAllDrives=True,
            ).execute()
            return int(metadata.get("size") or 0)
        except Exception:
            return 0

    def path(self, name):
        raise NotImplementedError("GoogleDriveMediaStorage does not support local paths.")
