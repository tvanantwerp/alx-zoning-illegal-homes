import os
import json
import zipfile
import requests


def read_json_file(file_path):
    """Read JSON file and return data."""
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def check_file_exists(file_name, data_folder="data"):
    """Check if file directory exists."""
    path = os.path.join(data_folder, file_name)
    return os.path.exists(path)


def download_file(url, file_name, data_folder="data", is_zip=True):
    """Download and optionally unzip file from URL."""
    file_path = (
        os.path.join(data_folder, f"{file_name}.zip")
        if is_zip
        else os.path.join(data_folder, f"{file_name}.csv")
    )

    # Download file
    response = requests.get(url, timeout=30)
    with open(file_path, "wb") as f:
        f.write(response.content)

    # Unzip if necessary
    if is_zip:
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(os.path.join(data_folder, file_name))
        os.remove(file_path)


def get_data(json_file_path="files.json", data_folder="../data"):
    """Download all files required for the project."""

    # Create data folder if not exists
    if not os.path.exists(data_folder):
        os.makedirs(data_folder)

    # Read JSON file
    file_data = read_json_file(json_file_path)

    # Download and unzip files
    for entry in file_data:
        file_name = entry["name"]
        url = entry["url"]
        is_zip = entry["filetype"] == "zip"

        if not check_file_exists(file_name, data_folder):
            download_file(url, file_name, data_folder, is_zip)


if __name__ == "__main__":
    get_data()
