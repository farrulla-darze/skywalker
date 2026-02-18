"""Setup script for Skywalker package."""
from setuptools import setup, find_packages

setup(
    name="skywalker",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.11,<4.0",
)
