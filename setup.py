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
    description="A tool for checking DICOM compliance against a reference model using Pydantic",
    author="Ashley Stewart",
    url="https://github.com/astewartau/dicompare",
    packages=find_packages(),
    py_modules=["dicompare"],
    entry_points={
        "console_scripts": [
            "dcm-gen-session=dicompare.cli.gen_session:main",
            "dicompare-session=dicompare.cli.check_session:main",
            "dicompare=dicompare.cli.start_web:main",
        ]
    },
    install_requires=[
        "pydicom==3.0.1",
        "pandas",
        "tabulate",
        "scipy"
    ],
    extras_require={
        "interactive": ["curses"]
    },
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    keywords="DICOM compliance validation medical imaging",
    package_data={
        "dicompare": ["docs/*.html"],
    },
    include_package_data=True,
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
)

