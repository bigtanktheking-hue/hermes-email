from setuptools import setup, find_packages
from pathlib import Path

requirements = Path("requirements.txt").read_text().strip().splitlines()

setup(
    name="mailtank-email",
    version="0.1.0",
    description="AI-powered email command center with Gmail integration",
    author="BigTankMusic",
    license="MIT",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "hermes=hermes.cli:main",
            "mailtank=hermes.cli:main",
        ],
    },
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Communications :: Email",
    ],
)
