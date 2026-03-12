from setuptools import setup, find_packages

setup(
    name="foodpanda-cli",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "rich>=13.0",
        "httpx>=0.27",
        "click>=8.0",
        "playwright>=1.40",
        "browser-cookie3>=0.20",
    ],
    entry_points={"console_scripts": ["fd=foodpanda.cli:cli"]},
)
