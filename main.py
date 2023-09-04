from downloader.download import get_data


def main():
    get_data("./downloader/files.json", "./data")


if __name__ == "__main__":
    main()
