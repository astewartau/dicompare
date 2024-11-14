from setuptools import setup, find_packages

setup(
    name="dcm-check",
    version="0.1.0",
    description="A tool for checking DICOM compliance against a reference model using Pydantic",
    author="Ashley Stewart",
    url="https://github.com/astewartau/BrainBench",
    packages=find_packages(),
    py_modules=["dcm_check"],
    entry_points={
        "console_scripts": [
            "dcm-check=dcm_check.cli:main",
            "generate-json-ref=dcm_check.generate_json_ref:main",
        ]
    },
    install_requires=[
        "pydicom==3.0.1",
        "pydantic",
        "pandas",
        "tabulate",
        "pytest",
    ],
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    keywords="DICOM compliance validation medical imaging",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
)

