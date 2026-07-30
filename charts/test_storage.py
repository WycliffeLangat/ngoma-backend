from django.test import SimpleTestCase, override_settings

from ngoma_backend.storage import GoogleDriveMediaStorage, _drive_file_id


class GoogleDriveStorageTests(SimpleTestCase):
    def test_drive_file_id_parses_stored_names(self):
        self.assertEqual(_drive_file_id("gdrive:abc123"), "abc123")
        self.assertEqual(_drive_file_id("gdrive/abc123"), "abc123")
        self.assertEqual(_drive_file_id("covers/local.jpg"), "")

    @override_settings(
        GOOGLE_DRIVE_STORAGE_FOLDER_ID="primary-folder",
        GOOGLE_DRIVE_MIRROR_FOLDER_IDS=["mirror-one", "mirror-two"],
        GOOGLE_DRIVE_PUBLIC_READ=True,
        GOOGLE_DRIVE_PUBLIC_PREFIXES=["covers/"],
        GOOGLE_DRIVE_URL_TEMPLATE="https://example.test/file/{file_id}",
    )
    def test_storage_uses_settings_without_google_api_call(self):
        storage = GoogleDriveMediaStorage()

        self.assertEqual(storage.folder_id, "primary-folder")
        self.assertEqual(storage.mirror_folder_ids, ["mirror-one", "mirror-two"])
        self.assertEqual(storage.url("gdrive:file-123"), "https://example.test/file/file-123")
        self.assertEqual(storage._should_share_publicly("covers/song.jpg"), True)
        self.assertEqual(storage._should_share_publicly("backups/db.json"), False)

    def test_storage_normalizes_comma_separated_mirror_folders(self):
        storage = GoogleDriveMediaStorage(
            folder_id="primary-folder",
            mirror_folder_ids="mirror-one, mirror-two",
        )

        self.assertEqual(storage.mirror_folder_ids, ["mirror-one", "mirror-two"])
