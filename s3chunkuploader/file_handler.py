import os
import boto3
import logging
import importlib

from django.utils.text import slugify
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from django.utils import timezone
from django.core.files.uploadhandler import FileUploadHandler
from django.db.models import FileField
from storages.backends.s3boto3 import S3Boto3StorageFile, S3Boto3Storage
from django.conf import settings


def get_setting(name, default=None):
    """
    Tries to get a prefixed setting key, if not present try to get a non prefixed key,
    if all fails return the default

    Arguments:
        name {string} -- The key name to look for
        default {any} -- The value to return if no key is found
    """
    return getattr(settings, f'CHUNK_UPLOADER_{name}', getattr(settings, name, default))

logger = logging.getLogger(__name__)
# get some settings
AWS_ACCESS_KEY_ID = get_setting('AWS_ACCESS_KEY_ID')  # Required
AWS_SECRET_ACCESS_KEY = get_setting('AWS_SECRET_ACCESS_KEY')  # Required
AWS_REGION = get_setting('AWS_REGION', None)
S3_DOCUMENT_ROOT_DIRECTORY = get_setting('S3_DOCUMENT_ROOT_DIRECTORY', '')
S3_APPEND_DATETIME_ON_UPLOAD = get_setting('S3_APPEND_DATETIME_ON_UPLOAD', True)
S3_PREFIX_QUERY_PARAM_NAME = get_setting('S3_PREFIX_QUERY_PARAM_NAME', '__prefix')
S3_MIN_PART_SIZE = get_setting('S3_MIN_PART_SIZE', 5 * 1024 * 1024)
CLEAN_FILE_NAME = get_setting('CLEAN_FILE_NAME', False)
MAX_UPLOAD_SIZE = get_setting('MAX_UPLOAD_SIZE', None)
S3_ENDPOINT_URL = get_setting('AWS_S3_ENDPOINT_URL', None)
S3_GENERATE_OBJECT_KEY_FUNCTION = get_setting('S3_GENERATE_OBJECT_KEY_FUNCTION', None)
AWS_STORAGE_BUCKET_NAME = get_setting('AWS_STORAGE_BUCKET_NAME', None)


# if a custom key generation function is provided, import it and prepare it for use
if S3_GENERATE_OBJECT_KEY_FUNCTION:
    func_parts = S3_GENERATE_OBJECT_KEY_FUNCTION.split('.')
    module = importlib.import_module('.'.join(func_parts[0:-1]))
    generate_object_key = getattr(module, func_parts[-1])
else:
    def generate_object_key(request, filename):
        """
        Derive the object key for S3 (Default implementation):
        The path is made out of the S3_DOCUMENT_ROOT_DIRECTORY if set,
        and uses specialised query params to determine any additional prefixes.
        The current upload time it appended to the file. To prevent that,
        set S3_APPEND_DATETIME_ON_UPLOAD to False in setings.
        By default, the following query parameter can be provided in the request url:
            __prefix = this will be used as a prefix for the object key (double underscore)
        To change the query param name, the setting S3_PREFIX_QUERY_PARAM_NAME can be set.
        """
        filename_base, filename_ext = os.path.splitext(filename)
        _now_postfix = ''
        if S3_APPEND_DATETIME_ON_UPLOAD:
            _now_postfix = f'_{timezone.now().strftime("%Y%m%d%H%M%S")}'
        _filename = f'{filename_base}{_now_postfix}{filename_ext}'
        path = Path(S3_DOCUMENT_ROOT_DIRECTORY)
        if S3_PREFIX_QUERY_PARAM_NAME:
            prefix = request.GET.get(S3_PREFIX_QUERY_PARAM_NAME)
            if prefix:
                path /= prefix
        path /= _filename
        return str(path)


class S3Wrapper(object):
    """
    A wrapper around the S3 client ensuring only one client is instantiated and reused.
    """
    _s3_client = None

    @classmethod
    def get_client(cls):
        if not cls._s3_client:
            logger.debug('Instantiating S3 client')
            extra_kwargs = {}
            if S3_ENDPOINT_URL:
                extra_kwargs['endpoint_url'] = S3_ENDPOINT_URL

            cls._s3_client = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION,
                **extra_kwargs)
        return cls._s3_client


def s3_client():
    """
    A handy method to get a reusable S3 client
    """
    return S3Wrapper.get_client()


class UploadFailed(Exception):
    pass


class ThreadedS3ChunkUploader(ThreadPoolExecutor):
    """
    A specialised ThreadPoolExecutor to upload files into S3 using multiple threads.
    The uploader maintains an internal queue. As chunks are added, they are appended
    to the queue. When the queue reaches a total size of over 5MB, the minimum size
    for S3 parts, it is then submitted as a future to the thread pool.
    Note that the part size can be configured with the S3_MIN_PART_SIZE setting
    """
    def __init__(self, client, bucket, key, upload_id, max_workers=None):
        """Initialise a new ThreadedS3ChunkUploader

        Arguments:
            client {object} -- S3 client
            bucket {str} -- Bucket name
            key {str} -- File S3 key
            upload_id {str} -- MultiPart upload id from S3
            max_workers {int} -- Max number of threads [10]
        """
        max_workers = max_workers or 10
        self.bucket = bucket
        self.key = key
        self.upload_id = upload_id
        self.client = client
        self.part_number = 0
        self.parts = []
        self.queue = []
        self.current_queue_size = 0
        super().__init__(max_workers=max_workers)

    def add(self, body):
        """Add a chunk to the internal queue. When the queue's size surpasses
        5MB (the min chunk size for S3), it is then packaged into a future
        and loaded into the threadpool.

        Arguments:
            body {bytes} -- A file chunk
        """
        if body:
            content_length = len(body)
            self.queue.append(body)
            self.current_queue_size += content_length

        if not body or self.current_queue_size > S3_MIN_PART_SIZE:
            self.part_number += 1
            _body = self.drain_queue()
            future = self.submit(
                self.client.upload_part,
                Bucket=self.bucket,
                Key=self.key,
                PartNumber=self.part_number,
                UploadId=self.upload_id,
                Body=_body,
                ContentLength=len(_body),
            )
            self.parts.append((self.part_number, future))
            logger.debug('Prepared part %s', self.part_number)

    def drain_queue(self):
        """Drain the internal queue. This happens when the internal queue
        passes the size defined in S3_MIN_PART_SIZE (defaults to 5MB)

        Returns:
            [bytes] -- The current queue part
        """
        body = b''.join(self.queue)
        self.queue = []
        self.current_queue_size = 0
        return body

    def get_parts(self):
        """Return the result of all the futures held in self.parts

        Returns:
            [list<dict>] -- S3 ready list of part dicts
        """
        return [{
            'PartNumber': part[0],
            'ETag': part[1].result()['ETag'],
            } for part in self.parts
        ]


class S3FileUploadHandler(FileUploadHandler):
    """
    Upload handler that streams data direct into S3.
    The upload handler will ultimately return a S3Boto3StorageFile,
    compatiable with django-storages.
    """
    def new_file(self, *args, **kwargs):
        """
        Create the file object to append to as data is coming in.
        """
        # If content_length is provided and file size is larger than the maximum allowed, then abort
        # Note that as per Django docs, content_length is not guaranteed to be provided.
        if MAX_UPLOAD_SIZE and self.content_length:
            if self.content_length > MAX_UPLOAD_SIZE:
                raise UploadFailed('File too large')

        super().new_file(*args, **kwargs)
        self.parts = []
        self.bucket_name = AWS_STORAGE_BUCKET_NAME
        file_name = self.file_name
        if CLEAN_FILE_NAME:
            file_name = slugify(self.file_name)
        self.s3_key = generate_object_key(self.request, file_name)
        self.client = s3_client()
        self.multipart = self.client.create_multipart_upload(
            Bucket=self.bucket_name,
            Key=self.s3_key,
            ContentType=self.content_type,
        )
        self.upload_id = self.multipart['UploadId']
        self.executor = ThreadedS3ChunkUploader(
            self.client,
            self.bucket_name,
            key=self.s3_key,
            upload_id=self.upload_id
        )

        # prepare a storages object as a file placeholder
        self.storage = S3Boto3Storage()
        self.file = S3Boto3StorageFile(self.s3_key, 'w', self.storage)
        self.file.original_name = self.file_name
        self.file.content_type = self.content_type
        self.file.charset = self.charset

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding):
        self.request = input_data
        self.content_length = content_length
        self.META = META
        return None

    def receive_data_chunk(self, raw_data, start):
        """
        Receive a single file chunk from the browser
        and add it to the executor
        """
        try:
            self.executor.add(raw_data)
        except Exception as exc:
            self.abort(exc)

    def file_complete(self, file_size):
        """
        Triggered when the last chuck of the file is received and handled.
        """
        # Add an empty body to drain the executor queue
        self.executor.add(None)
        # collect all the file parts from the executor
        parts = self.executor.get_parts()
        # complete the multiplart upload
        _result = self.client.complete_multipart_upload(
            Bucket=self.bucket_name,
            Key=self.s3_key,
            UploadId=self.upload_id,
            MultipartUpload={
                'Parts': parts
            }
        )
        # shutdown the executor and set the final file size on the file
        self.executor.shutdown()
        self.file.file_size = file_size
        # close the file placeholder
        self.file.close()
        return self.file

    def abort(self, exception):
        closed = self.file.close()
        self.client.abort_multipart_upload(
            Bucket=self.bucket_name,
            Key=self.s3_key,
            UploadId=self.upload_id,
        )
        raise UploadFailed(exception)
