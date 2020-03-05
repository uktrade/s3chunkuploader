import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.fixtures.settings")

import unittest
from django.test import override_settings
import s3chunkuploader.file_handler

class TestPrefixedKeys(unittest.TestCase):

    @override_settings(CHUNK_UPLOADER_AWS_ACCESS_KEY_ID = 'prefix_key')
    def test_prefixed_key_found(self):
        self.assertEqual('prefix_key', s3chunkuploader.file_handler.get_setting('AWS_ACCESS_KEY_ID'))

    @override_settings(AWS_ACCESS_KEY_ID = 'non_prefixed_key')
    def test_prefixed_key_not_found(self):
        self.assertEqual('non_prefixed_key', s3chunkuploader.file_handler.get_setting('AWS_ACCESS_KEY_ID'))

    @override_settings(CHUNK_UPLOADER_AWS_ACCESS_KEY_ID = 'prefix_key')
    @override_settings(AWS_ACCESS_KEY_ID = 'non_prefixed_key')
    def test_get_setting_when_both_keys_are_found(self):
        self.assertEqual('prefix_key', s3chunkuploader.file_handler.get_setting('AWS_ACCESS_KEY_ID'))

    def test_return_default_value(self):
        self.assertEqual('default', s3chunkuploader.file_handler.get_setting('AWS_ACCESS_KEY_ID', 'default'))

if __name__ == '__main__':
    unittest.main()