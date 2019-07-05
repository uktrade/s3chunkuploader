=================
S3 Chunk Uploader
=================

A Django file handler to manage piping uploaded files directly to S3 without passing through the server's file system.
The uploader uses multiple threads to speed up the upload of larger files.
This package relies on Django and Django-Storages, allowing the use of the S3 storages FileField but changes the
upload behaviour to bypass local file system.


Quick start
-----------

#. Install the package:

    pip install s3chunkuploader


#. Set the Django FILE_UPLOAD_HANDLERS setting:

    FILE_UPLOAD_HANDLERS = ('s3chunkuploader.file_handler.S3FileUploadHandler',)


How it works
------------
The File Handler intercepts the file upload multipart request at the door, and as chunks of the file are received from the
browser, they are collectd into an internal queue within custom ThreadPoolWorker. When the queue surpasses a configurable
size (by default 5MB which is the minimum Part size for S3 multipart upload), it is submitted to the Thread Pool
as a Future which will then resolve. Once all the chunks are uploaded and all the futures are resolved the upload is complete.
By default 10 threads are used which means a 100MB file upload can be potentially sent as 20 5MB parts to S3.

The FileHandler ultimately returns a 'dummy' django-storages S3Boto3StorageFile which is compatible with the storages
S3 File Field, but was not actually used to upload a full file.  The file is also enhanced with two additional attributes:

    original_name: The original file name uploaded
    file_size: The actual full file size uploaded


It is recommended to bypass csrf checks on the upload file view as the csrf check will read the POST params before the
handler is used.
A replacement file field S3FileField is provided in fields.py and is satisfied with the S3 object key

Settings
--------

The following settings are expected in your Django application (only 2 are required)

============================ =====================================================================================================
Setting                      Description
============================ =====================================================================================================
AWS_ACCESS_KEY_ID            Required. Your AWS access key
AWS_SECRET_ACCESS_KEY        Required. The AWS secret
AWS_REGION                   Optional. Region of S3 bucket
S3_DOCUMENT_ROOT_DIRECTORY   Optional. Document root for all uploads (prefix)
S3_APPEND_DATETIME_ON_UPLOAD Optional [True]. Appent the current datetime sring to the uploaded file name
S3_PREFIX_QUERY_PARAM_NAME   Optional [__prefix]. A query param key name which provides additional prefix for the object key on S3
S3_MIN_PART_SIZE             Optional [5MB]. The part size to upload to S3
============================ =====================================================================================================
