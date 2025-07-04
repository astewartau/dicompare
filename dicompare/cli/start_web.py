import os
import logging
import webbrowser
from importlib.resources import files

logger = logging.getLogger(__name__)

def main():
    # Get the package base directory using `importlib.resources`
    package_dir = files("dicompare").joinpath("docs", "index.html")

    # Convert the resource path to an absolute file path
    docs_path = str(package_dir)

    # Check if the file exists
    if not os.path.exists(docs_path):
        logger.error(f"Documentation not found at {docs_path}.")
        return

    # Open the documentation in the default web browser
    webbrowser.open(f"file://{docs_path}")
