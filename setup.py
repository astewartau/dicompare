from setuptools import setup, find_packages

setup(
    name="dcm-check",
    version="0.1.2",
    description="A tool for checking DICOM compliance against a reference model using Pydantic",
    author="Ashley Stewart",
    url="https://github.com/astewartau/BrainBench",
    packages=find_packages(),
    py_modules=["dcm_check"],
    entry_points={
        "console_scripts": [
            "dcm-check=dcm_check.dcm_check:main",
            "dcm-gen-session=dcm_check.dcm_gen_session:main",
            "dcm-read-session=dcm_check.dcm_read_session:main",
            "dcm-check-session=dcm_check.dcm_check_session:main",
        ]
    },
    install_requires=[
        "pydicom==3.0.1",
        "pydantic",
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
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
)

