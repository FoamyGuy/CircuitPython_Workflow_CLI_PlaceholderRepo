# SPDX-FileCopyrightText: 2019 Nicholas Tollervey, written for Adafruit Industries
# SPDX-FileCopyrightText: 2023 Tim Cocks, written for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
Utilities that are shared and used by both click CLI command functions
and Backend class functions.
"""
import glob
import os
import re
import json
import appdirs
import pkg_resources
import requests

#: Version identifier for a bad MPY file format
BAD_FILE_FORMAT = "Invalid"

#: The location of data files used by circup (following OS conventions).
DATA_DIR = appdirs.user_data_dir(appname="circfile", appauthor="adafruit")

#: Module formats list (and the other form used in github files)
PLATFORMS = {"py": "py", "8mpy": "8.x-mpy", "9mpy": "9.x-mpy"}

#: Timeout for requests calls like get()
REQUESTS_TIMEOUT = 30

#: Commands that do not require an attached board
BOARDLESS_COMMANDS = ["show", "bundle-add", "bundle-remove", "bundle-show"]


def get_latest_release_from_url(url, logger):
    """
    Find the tag name of the latest release by using HTTP HEAD and decoding the redirect.

    :param str url: URL to the latest release page on a git repository.
    :return: The most recent tag value for the release.
    """

    logger.info("Requesting redirect information: %s", url)
    response = requests.head(url, timeout=REQUESTS_TIMEOUT)
    responseurl = response.url
    if response.is_redirect:
        responseurl = response.headers["Location"]
    tag = responseurl.rsplit("/", 1)[-1]
    logger.info("Tag: '%s'", tag)
    return tag
