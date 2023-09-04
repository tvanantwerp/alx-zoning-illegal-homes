import os
import json
import requests


def read_json_file(file_path: str):
    """Read JSON file and return data."""
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def check_file_exists(file_name: str, data_folder: str):
    """Check if file directory exists."""
    path = os.path.join(data_folder, file_name)
    return os.path.exists(path)


def download_file(url: str, file_name: str, file_type: str, data_folder: str):
    """Download file from URL."""
    file_path = os.path.join(data_folder, f"{file_name}.{file_type}")

    # Download file
    response = requests.get(url, timeout=30)
    with open(file_path, "wb") as f:
        f.write(response.content)


def get_data():
    """Download all files required for the project."""

    current_dir = os.path.dirname(__file__)
    data_folder = os.path.join(current_dir, "..", "..", "data")
    json_file_path = os.path.join(current_dir, "files.json")

    # Create data folder if not exists
    if not os.path.exists(data_folder):
        os.makedirs(data_folder)

    # Read JSON file
    file_data = read_json_file(json_file_path)

    # Download and unzip files
    for entry in file_data:
        file_name = entry["name"]
        url = entry["url"]
        file_type = entry["filetype"]

        if not check_file_exists(file_name, data_folder):
            download_file(url, file_name, file_type, data_folder)


if __name__ == "__main__":
    get_data()
