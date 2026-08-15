import os
from setuptools import setup, find_packages

# Read the version from the package __init__.py file
version = {}
with open(os.path.join("dicompare", "__init__.py")) as f:
    for line in f:
        if line.startswith("__version__"):
            exec(line, version)
            break

setup(
    name="dicompare",
    version=version["__version__"],
    description="A tool for checking DICOM compliance against a template",
    author="Ashley Stewart",
    url="https://github.com/astewartau/dicompare",
    packages=find_packages(),
    py_modules=["dicompare"],
    entry_points={
        "console_scripts": [
            "dicompare=dicompare.cli.main:main",
        ]
    },
    # Lower bounds only (no upper caps except pydicom, which has breaking changes
    # in 3.0). Floors are kept at or below the versions bundled by Pyodide 0.27.0
    # — pandas 2.2.3 / scipy 1.14.1 / numpy 2.0.2 / tqdm 4.66.2 / jsonschema 4.21.1
    # — because the web build resolves the compiled packages from Pyodide, so a
    # floor above those would break `micropip.install('dicompare')` in the browser.
    install_requires=[
        "pydicom>=2.4.5,<3",
        "pandas>=2.0",
        "tabulate>=0.9.0",
        "scipy>=1.10",
        "tqdm>=4.60",
        "nibabel>=5.0.0",
        "twixtools>=0.24",
        "jsonschema>=4.18",
    ],
    extras_require={
        "interactive": ["curses"],
        "test": ["pytest-asyncio"]
    },
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    keywords="DICOM compliance validation medical imaging",
    include_package_data=True,
    package_data={
        "dicompare": [
            "metaschema.json",
            "schemas/*.json",
        ],
    },
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
)

