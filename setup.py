from setuptools import setup, find_packages
from pathlib import Path

requirements = Path("requirements.txt").read_text().strip().splitlines()

setup(
    name="hermes-email",
    version="0.1.0",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "hermes=hermes.cli:main",
        ],
    },
    python_requires=">=3.9",
)
