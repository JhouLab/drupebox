#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import time
import dropbox
from datetime import datetime

drupebox_cache_store_path = "/dev/shm/drupebox_last_seen_files"

# To customise this code, change the app key below
# Get your app key from the Dropbox developer website for your app
app_key = "1skff241na3x0at"


def note(text):
    print(">>> " + text)


def fyi(text):
    print("    " + text)

def fyi_ignore(text):
    print("        ignore " + text)

def get_config_real():
    from configobj import ConfigObj

    if not path_exists(os.path.join(os.getenv("HOME"), ".config")):
        os.makedirs(os.path.join(os.getenv("HOME"), ".config"))
    config_filename = os.path.join(os.getenv("HOME"), ".config", "drupebox")
    if not path_exists(config_filename):
        config = ConfigObj()
        config.filename = config_filename

        flow = dropbox.DropboxOAuth2FlowNoRedirect(
            app_key, use_pkce=True, token_access_type="offline"
        )
        authorize_url = flow.start()
        print(("1. Go to: " + authorize_url))
        print('2. Click "Allow" (you might have to log in first)')
        print("3. Copy the authorization code.")
        code = input("Enter the authorization code here: ").strip()
        result = flow.finish(code)

        (config["access_token"], config["user_id"], config["refresh_token"]) = (
            result.access_token,
            result.user_id,
            result.refresh_token,
        )
        config["dropbox_local_path"] = input(
            "Enter dropbox local path (or press enter for "
            + os.path.join(os.getenv("HOME"), "Dropbox")
            + "/) "
        ).strip()
        if config["dropbox_local_path"] == "":
            config["dropbox_local_path"] = (
                os.path.join(os.getenv("HOME"), "Dropbox") + "/"
            )
        if config["dropbox_local_path"][-1] != "/":
            config["dropbox_local_path"] = config["dropbox_local_path"] + "/"
        if not path_exists(config["dropbox_local_path"]):
            os.makedirs(config["dropbox_local_path"])
        config["max_file_size"] = 10000000
        config["excluded_paths"] = [
            '"/home/pi/SUPER SECRET LOCATION 1"',
            '"/home/pi/SUPER SECRET LOCATION 2"',
        ]
        config.write()

    config = ConfigObj(config_filename)
    return config


def get_config():
    if get_config.cache == "":  # First run
        get_config.cache = get_config_real()
    return get_config.cache


get_config.cache = ""


def get_live_tree():
    tree = []
    for (root, dirs, files) in os.walk(
        get_config()["dropbox_local_path"], topdown=True, followlinks=True
    ):
        for name in files:
            tree.append(os.path.join(root, name))
        for name in dirs:
            tree.append(os.path.join(root, name))
    tree.sort(
        key=lambda s: -len(s)
    )  # sort longest to smallest so that later files get deleted before the folders that they are in
    return tree


def store_tree(tree):
    tree = "\n".join(tree)
    with open(drupebox_cache_store_path, "wb") as f:
        f.write(bytes(tree.encode()))


def load_tree():
    if os.path.exists(drupebox_cache_store_path):
        last_tree = open(drupebox_cache_store_path, "r").read().split("\n")
    else:
        last_tree = [""]
    return last_tree


def determine_locally_deleted_files(tree_now, tree_last):
    deleted = []
    if tree_last == [""]:
        return []
    for element in tree_last:
        if not element in tree_now:
            deleted.append(element)
    return deleted


def upload(client, local_file_path, remote_file_path):
    print("uuu", local_file_path)
    f = open(local_file_path, "rb")
    client.files_upload(
        f.read(),
        remote_file_path,
        mute=True,
        mode=dropbox.files.WriteMode("overwrite", None),
    )


def download(client, remote_file_path, local_file_path):
    print("ddd", remote_file_path)
    client.files_download_to_file(local_file_path, remote_file_path)


def unix_time(readable_time):
    return time.mktime(readable_time.timetuple())


def readable_time(unix_time):
    return datetime.fromtimestamp(float(unix_time)).strftime(
        "%a, %d %b %Y %H:%M:%S +0000"
    )


def path_exists(path):
    return os.path.exists(path)


def local_item_modified_time(local_file_path):
    return os.path.getmtime(local_file_path)


def fp(path):
    # Fix path function as dropbox root folder is "" not "/"
    if path == "":
        return path
    if path == "/":
        return ""
    else:
        if path[0] != "/":
            return "/" + path
        else:
            return path


def fix_local_time(client, remote_file_path):
    remote_folder_path = "/".join(
        remote_file_path.split("/")[0:-1]
    )  # path excluding file, i.e. just to the folder
    note("fix local time on " + remote_file_path)

    remote_folder = client.files_list_folder(fp(remote_folder_path)).entries
    for remote_file in remote_folder:
        if remote_file.path_display == remote_file_path:
            # matched the file we are looking for
            file_modified_time = remote_file.client_modified
            local_file_path = get_config()["dropbox_local_path"] + remote_file_path
            os.utime(
                local_file_path,
                (
                    int(unix_time(file_modified_time)),
                    int(unix_time(file_modified_time)),
                ),
            )
            return  # found file so no further looping required


def skip(local_file_path):
    local_item = local_file_path.split("/")[-1]
    if local_item[0 : len(".fuse_hidden")] == ".fuse_hidden":
        fyi_ignore("fuse hidden files")
        return True
    if local_item[-len(".pyc") :] == ".pyc":
        fyi_ignore(".pyc files")
        return True
    if local_item[-len("__pycache__") :] == "__pycache__":
        fyi_ignore("__pycache__")
        return True
    if local_item in [".DS_Store", "._.DS_Store", "DG1__DS_DIR_HDR", "DG1__DS_VOL_HDR"]:
        fyi_ignore(local_item)
        return True

    try:
        local_time = local_item_modified_time(local_file_path)
    except:
        print(("crash on local time check on", local_item))
        return True
    return False


def local_item_not_found_at_remote(remote_folder, remote_file_path):
    remote_path = remote_file_path
    extra_path = "/".join(remote_path.split("/")[0:-1])
    remote_folder_path = extra_path

    unnaccounted_local_file = True
    for remote_item in remote_folder:
        if remote_item.path_display == remote_file_path:
            unnaccounted_local_file = False
    return unnaccounted_local_file


def remote_item_modified_with_deleted(client, remote_file_path):
    remote_path = remote_file_path
    extra_path = "/".join(remote_path.split("/")[0:-1])
    remote_folder_path = extra_path
    remote_folder_with_deleted = client.files_list_folder(
        fp(remote_folder_path), include_deleted=True
    ).entries
    folder_with_deleted = remote_folder_with_deleted
    remote_time = 0
    for unn_item in folder_with_deleted:
        print(unn_item)
        if unn_item.path_display == remote_file_path:
            if isinstance(unn_item, dropbox.files.DeletedMetadata):
                remote_time = unix_time(unn_item.client_modified)
                break
    return remote_time
