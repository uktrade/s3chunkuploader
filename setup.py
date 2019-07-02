import os
from setuptools import find_packages, setup
from s3chunkuploader import __version__, __author__, __email__


with open(os.path.join(os.path.dirname(__file__), 'README.rst')) as readme:
    README = readme.read()

# allow setup.py to be run from any path
os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

setup(
    name='s3chunkuploader',
    version=__version__,
    packages=find_packages(),
    include_package_data=True,
    license='MIT',
    description='A Django/Django-Storages threaded S3 chunk uploader',
    long_description=README,
    url='https://github.com/uktrade/s3chunkuploader',
    author=__author__,
    author_email=__email__,
    classifiers=[
        'Environment :: Web Environment',
        'Framework :: Django',
        'Framework :: Django :: 2.0',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
    install_requires=[
        'Django',
        'django-storages',
    ]
)