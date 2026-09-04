from setuptools import find_packages, setup

setup(
    name="mailguard",
    version="1.0.0",
    description="Secure async CLI email sending system with encrypted configuration and audit logging",
    author="Kavin",
    python_requires=">=3.11",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=[
        "cryptography>=42.0.0",
        "aiosmtplib>=3.0.0",
    ],
    extras_require={
        "dev": ["pytest>=8.0.0", "pytest-asyncio>=0.23.0"],
    },
    entry_points={
        "console_scripts": [
            "mailguard=cli.main:main",
        ],
    },
)
