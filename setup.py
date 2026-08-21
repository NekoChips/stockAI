from setuptools import find_packages, setup


setup(
    name="stock-ai-agent",
    version="0.1.1",
    description="A-share and ETF paper-trading AI agent for Shanghai/Shenzhen markets.",
    python_requires=">=3.9",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=["alphafeed==0.1.4", "akshare==1.15.60", "PyMySQL==1.1.1"],
    package_data={"stock_ai_agent": ["dashboard.html"]},
)
