# SPDX-FileCopyrightText: 2019 Nicholas Tollervey, 2024 Tim Cocks, written for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
Functions called from commands in order to provide behaviors and return information.
"""

import ctypes
import glob
import os

from subprocess import check_output
import sys
import shutil
import zipfile
import json
import re
import toml
import findimports
import requests
import click

from circup.shared import (
    PLATFORMS,
    REQUESTS_TIMEOUT,
    _get_modules_file,
    BUNDLE_CONFIG_OVERWRITE,
    BUNDLE_CONFIG_FILE,
    BUNDLE_CONFIG_LOCAL,
    BUNDLE_DATA,
    NOT_MCU_LIBRARIES,
    tags_data_load,
)
from circup.logging import logger
from circup.module import Module
from circup.bundle import Bundle



def completion_for_install(ctx, param, incomplete):
    """
    Returns the list of available modules for the command line tab-completion
    with the ``circup install`` command.
    """
    # pylint: disable=unused-argument
    available_modules = get_bundle_versions(get_bundles_list(), avoid_download=True)
    module_names = {m.replace(".py", "") for m in available_modules}
    if incomplete:
        module_names = [name for name in module_names if name.startswith(incomplete)]
        module_names.extend(glob.glob(f"{incomplete}*"))
    return sorted(module_names)


def completion_for_example(ctx, param, incomplete):
    """
    Returns the list of available modules for the command line tab-completion
    with the ``circup example`` command.
    """
    # pylint: disable=unused-argument, consider-iterating-dictionary
    available_examples = get_bundle_examples(get_bundles_list(), avoid_download=True)

    matching_examples = [
        example_path
        for example_path in available_examples.keys()
        if example_path.startswith(incomplete)
    ]

    return sorted(matching_examples)


def find_device():
    """
    Return the location on the filesystem for the connected CircuitPython device.
    This is based upon how Mu discovers this information.

    :return: The path to the device on the local filesystem.
    """
    device_dir = None
    # Attempt to find the path on the filesystem that represents the plugged in
    # CIRCUITPY board.
    if os.name == "posix":
        # Linux / OSX
        for mount_command in ["mount", "/sbin/mount"]:
            try:
                mount_output = check_output(mount_command).splitlines()
                mounted_volumes = [x.split()[2] for x in mount_output]
                for volume in mounted_volumes:
                    if volume.endswith(b"CIRCUITPY"):
                        device_dir = volume.decode("utf-8")
            except FileNotFoundError:
                continue
    elif os.name == "nt":
        # Windows

        def get_volume_name(disk_name):
            """
            Each disk or external device connected to windows has an attribute
            called "volume name". This function returns the volume name for the
            given disk/device.

            Based upon answer given here: http://stackoverflow.com/a/12056414
            """
            vol_name_buf = ctypes.create_unicode_buffer(1024)
            ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(disk_name),
                vol_name_buf,
                ctypes.sizeof(vol_name_buf),
                None,
                None,
                None,
                None,
                0,
            )
            return vol_name_buf.value

        #
        # In certain circumstances, volumes are allocated to USB
        # storage devices which cause a Windows popup to raise if their
        # volume contains no media. Wrapping the check in SetErrorMode
        # with SEM_FAILCRITICALERRORS (1) prevents this popup.
        #
        old_mode = ctypes.windll.kernel32.SetErrorMode(1)
        try:
            for disk in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                path = "{}:\\".format(disk)
                if os.path.exists(path) and get_volume_name(path) == "CIRCUITPY":
                    device_dir = path
                    # Report only the FIRST device found.
                    break
        finally:
            ctypes.windll.kernel32.SetErrorMode(old_mode)
    else:
        # No support for unknown operating systems.
        raise NotImplementedError('OS "{}" not supported.'.format(os.name))
    logger.info("Found device: %s", device_dir)
    return device_dir



def get_circup_version():
    """Return the version of circup that is running. If not available, return None.

    :return: Current version of circup, or None.
    """
    try:
        from importlib import metadata  # pylint: disable=import-outside-toplevel
    except ImportError:
        try:
            import importlib_metadata as metadata  # pylint: disable=import-outside-toplevel
        except ImportError:
            return None
    try:
        return metadata.version("circup")
    except metadata.PackageNotFoundError:
        return None


def tags_data_save_tag(key, tag):
    """
    Add or change the saved tag value for a bundle.

    :param str key: The bundle's identifier/key.
    :param str tag: The new tag for the bundle.
    """
    tags_data = tags_data_load(logger)
    tags_data[key] = tag
    with open(BUNDLE_DATA, "w", encoding="utf-8") as data:
        json.dump(tags_data, data)


def get_device_path(host, password, path):
    """
    :param host Hostname or IP address.
    :param password REST API password.
    :param path File system path.
    :return device URL or None if the device cannot be found.
    """
    if path:
        device_path = path
    elif host:
        # pylint: enable=no-member
        device_path = f"http://:{password}@" + host
    else:
        device_path = find_device()
    return device_path


def sorted_by_directory_then_alpha(list_of_files):
    dirs = {}
    files = {}
    
    for cur_file in list_of_files:
        if cur_file["directory"]:
            dirs[cur_file["name"]] = cur_file
        else:
            files[cur_file["name"]] = cur_file
    
    sorted_dir_names = sorted(dirs.keys())
    sorted_file_names = sorted(files.keys())
    
    sorted_full_list = []
    for cur_name in sorted_dir_names:
        sorted_full_list.append(dirs[cur_name])
    for cur_name in sorted_file_names:
        sorted_full_list.append(files[cur_name])
    
    return sorted_full_list