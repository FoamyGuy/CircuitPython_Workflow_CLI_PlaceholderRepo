# SPDX-FileCopyrightText: 2019 Nicholas Tollervey, written for Adafruit Industries
# SPDX-FileCopyrightText: 2023 Tim Cocks, written for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
Backend classes that represent interfaces to physical devices.
"""
import os
import shutil
import sys
import socket
import tempfile
from urllib.parse import urlparse, urljoin
import click
import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth

from circup.shared import DATA_DIR, BAD_FILE_FORMAT, extract_metadata, _get_modules_file

#: The location to store a local copy of code.py for use with --auto and
#  web workflow
LOCAL_CODE_PY_COPY = os.path.join(DATA_DIR, "code.tmp.py")


class Backend:
    """
    Backend parent class to be extended for workflow specific
    implementations
    """

    def __init__(self, logger):
        self.device_location = None
        self.logger = logger


    def _create_library_directory(self, device_path, library_path):
        """
        To be overridden by subclass
        """
        raise NotImplementedError

    def upload_file(self, target_file, location_to_paste):
        """Paste a copy of the specified file at the location given
        To be overridden by subclass
        """
        raise NotImplementedError


    def get_file_path(self, filename):
        """
        To be overridden by subclass
        """
        raise NotImplementedError

    def get_free_space(self):
        """
        To be overridden by subclass
        """
        raise NotImplementedError

    def is_device_present(self):
        """
        To be overriden by subclass
        """
        raise NotImplementedError


    def file_exists(self, filepath):
        """
        To be overriden by subclass
        """
        raise NotImplementedError


def _writeable_error():
    click.secho(
        "CircuitPython Web Workflow Device not writable\n - "
        "Remount storage as writable to device (not PC)",
        fg="red",
    )
    sys.exit(1)


class WebBackend(Backend):
    """
    Backend for interacting with a device via Web Workflow
    """

    def __init__(self, host, password, logger, timeout=10):
        super().__init__(logger)
        if password is None:
            raise ValueError("Must pass --password or set CIRCUP_WEBWORKFLOW_PASSWORD environment variable")

        # pylint: disable=no-member
        # verify hostname/address
        try:
            socket.getaddrinfo(host, 80, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise RuntimeError(
                "Invalid host: {}.".format(host) + " You should remove the 'http://'"
                if "http://" in host or "https://" in host
                else "Could not find or connect to specified device"
            ) from exc

        self.FS_PATH = "fs/"
        
        self.LIB_DIR_PATH = f"{self.FS_PATH}lib/"
        self.host = host
        self.password = password
        self.device_location = f"http://:{self.password}@{self.host}"

        self.session = requests.Session()
        self.session.mount(self.device_location, HTTPAdapter(max_retries=5))
        self.library_path = self.device_location + "/" + self.LIB_DIR_PATH
        self.timeout = timeout
        self.FS_URL = urljoin(self.device_location, self.FS_PATH)
        
        
    def install_file_http(self, source, location=None):
        """
        Install file to device using web workflow.
        :param source source file.
        :param location the location on the device to copy the source
          directory in to. If omitted is CIRCUITPY/lib/ used.
        """
        file_name = source.split(os.path.sep)
        file_name = file_name[-2] if file_name[-1] == "" else file_name[-1]

        if location is None:
            target = self.device_location + "/" + self.LIB_DIR_PATH + file_name
        else:
            target = self.device_location + "/" + self.FS_PATH + location + file_name

        auth = HTTPBasicAuth("", self.password)

        with open(source, "rb") as fp:
            r = self.session.put(target, fp.read(), auth=auth, timeout=self.timeout)
            if r.status_code == 409:
                _writeable_error()
            r.raise_for_status()

    def install_dir_http(self, source, location=None):
        """
        Install directory to device using web workflow.
        :param source source directory.
        :param location the location on the device to copy the source
          directory in to. If omitted is CIRCUITPY/lib/ used.
        """
        mod_name = source.split(os.path.sep)
        mod_name = mod_name[-2] if mod_name[-1] == "" else mod_name[-1]
        if location is None:
            target = self.device_location + "/" + self.LIB_DIR_PATH + mod_name
        else:
            target = self.device_location + "/" + self.FS_PATH + location + mod_name
        target = target + "/" if target[:-1] != "/" else target
        url = urlparse(target)
        auth = HTTPBasicAuth("", url.password)

        # Create the top level directory.
        with self.session.put(target, auth=auth, timeout=self.timeout) as r:
            if r.status_code == 409:
                _writeable_error()
            r.raise_for_status()

        # Traverse the directory structure and create the directories/files.
        for root, dirs, files in os.walk(source):
            rel_path = os.path.relpath(root, source)
            if rel_path == ".":
                rel_path = ""
            for name in dirs:
                path_to_create = (
                    urljoin(
                        urljoin(target, rel_path + "/", allow_fragments=False),
                        name,
                        allow_fragments=False,
                    )
                    if rel_path != ""
                    else urljoin(target, name, allow_fragments=False)
                )
                path_to_create = (
                    path_to_create + "/"
                    if path_to_create[:-1] != "/"
                    else path_to_create
                )

                with self.session.put(
                    path_to_create, auth=auth, timeout=self.timeout
                ) as r:
                    if r.status_code == 409:
                        _writeable_error()
                    r.raise_for_status()
            for name in files:
                with open(os.path.join(root, name), "rb") as fp:
                    path_to_create = (
                        urljoin(
                            urljoin(target, rel_path + "/", allow_fragments=False),
                            name,
                            allow_fragments=False,
                        )
                        if rel_path != ""
                        else urljoin(target, name, allow_fragments=False)
                    )
                    with self.session.put(
                        path_to_create, fp.read(), auth=auth, timeout=self.timeout
                    ) as r:
                        if r.status_code == 409:
                            _writeable_error()
                        r.raise_for_status()

    def _create_library_directory(self, device_path, library_path):
        url = urlparse(device_path)
        auth = HTTPBasicAuth("", url.password)
        with self.session.put(library_path, auth=auth, timeout=self.timeout) as r:
            if r.status_code == 409:
                _writeable_error()
            r.raise_for_status()

    def upload_file(self, target_file, location_to_paste):
        """
        copy a file from the host PC to the microcontroller
        :param target_file: file on the host PC to copy
        :param location_to_paste: Location on the microcontroller to paste it.
        :return: 
        """
        if os.path.isdir(target_file):
            create_directory_url = urljoin(
                self.device_location,
                "/".join(("fs", location_to_paste, target_file, "")),
            )
            self._create_library_directory(self.device_location, create_directory_url)
            self.install_dir_http(target_file)
        else:
            self.install_file_http(target_file)

    def download_file(self, target_file, location_to_paste):
        """
        Download a file from the MCU device to the local host PC
        :param target_file: The file on the MCU to download
        :param location_to_paste: The location on the host PC to put the downloaded copy.
        :return: 
        """
        auth = HTTPBasicAuth("", self.password)
        with self.session.get(self.FS_URL + target_file, timeout=self.timeout, auth=auth) as r:
            if r.status_code == 404:
                click.secho(f"{target_file} was not found on the device", "red")
            
            
            file_name = target_file.split("/")[-1]
            if location_to_paste is None:
                with open(file_name, "wb") as f:
                    f.write(r.content)
                
                click.echo(f"Downloaded File: {file_name}")
            else:
                with open(os.path.join(location_to_paste, file_name), "wb") as f:
                    f.write(r.content)

                click.echo(f"Downloaded File: {os.path.join(location_to_paste, file_name)}")
    
    def uninstall(self, device_path, module_path):
        """
        Uninstall given module on device using REST API.
        """
        url = urlparse(device_path)
        auth = HTTPBasicAuth("", url.password)
        with self.session.delete(module_path, auth=auth, timeout=self.timeout) as r:
            if r.status_code == 409:
                _writeable_error()
            r.raise_for_status()

    def update(self, module):
        """
        Delete the module on the device, then copy the module from the bundle
        back onto the device.

        The caller is expected to handle any exceptions raised.
        """
        self._update_http(module)

    def file_exists(self, filepath):
        """
        return True if the file exists, otherwise False.
        """
        auth = HTTPBasicAuth("", self.password)
        resp = requests.get(
            self.get_file_path(filepath), auth=auth, timeout=self.timeout
        )
        if resp.status_code == 200:
            return True
        return False

    def _update_http(self, module):
        """
        Update the module using web workflow.
        """
        if module.file:
            # Copy the file (will overwrite).
            self.install_file_http(module.bundle_path)
        else:
            # Delete the directory (recursive) first.
            url = urlparse(module.path)
            auth = HTTPBasicAuth("", url.password)
            with self.session.delete(module.path, auth=auth, timeout=self.timeout) as r:
                if r.status_code == 409:
                    _writeable_error()
                r.raise_for_status()
            self.install_dir_http(module.bundle_path)

    def get_file_path(self, filename):
        """
        retuns the full path on the device to a given file name.
        """
        return urljoin(
            urljoin(self.device_location, "fs/", allow_fragments=False),
            filename,
            allow_fragments=False,
        )

    def is_device_present(self):
        """
        returns True if the device is currently connected and running supported version
        """
        try:
            with self.session.get(f"{self.device_location}/cp/version.json") as r:
                r.raise_for_status()
                web_api_version = r.json().get("web_api_version")
                if web_api_version is None:
                    self.logger.error("Unable to get web API version from device.")
                    click.secho("Unable to get web API version from device.", fg="red")
                    return False

                if web_api_version < 4:
                    self.logger.error(
                        f"Device running unsupported web API version {web_api_version} < 4."
                    )
                    click.secho(
                        f"Device running unsupported web API version {web_api_version} < 4.",
                        fg="red",
                    )
                    return False
        except requests.exceptions.ConnectionError:
            return False

        return True

    def get_free_space(self):
        """
        Returns the free space on the device in bytes.
        """
        auth = HTTPBasicAuth("", self.password)
        with self.session.get(
            urljoin(self.device_location, "fs/"),
            auth=auth,
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        ) as r:
            r.raise_for_status()
            if r.json().get("free") is None:
                self.logger.error("Unable to get free block count from device.")
                click.secho("Unable to get free block count from device.", fg="red")
            elif r.json().get("block_size") is None:
                self.logger.error("Unable to get block size from device.")
                click.secho("Unable to get block size from device.", fg="red")
            elif r.json().get("writable") is None or r.json().get("writable") is False:
                self.logger.error(
                    "CircuitPython Web Workflow Device not writable\n - "
                    "Remount storage as writable to device (not PC)"
                )
                click.secho(
                    "CircuitPython Web Workflow Device not writable\n - "
                    "Remount storage as writable to device (not PC)",
                    fg="red",
                )
            else:
                return r.json()["free"] * r.json()["block_size"]  # bytes
            sys.exit(1)

    def list_dir(self, dirpath):
        auth = HTTPBasicAuth("", self.password)
        with self.session.get(
                urljoin(self.device_location, f"fs/{dirpath if dirpath else ''}"),
                auth=auth,
                headers={"Accept": "application/json"},
                timeout=self.timeout,
        ) as r:
            print(r.content)
            return r.json()["files"]