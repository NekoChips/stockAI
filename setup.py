from setuptools import find_packages, setup


setup(
    name="stock-ai-agent",
    version="0.1.1",
    description="A-share and ETF paper-trading AI agent for Shanghai/Shenzhen markets.",
    python_requires=">=3.9",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=["akshare>=1.15", "PyMySQL>=1.1"],
)
