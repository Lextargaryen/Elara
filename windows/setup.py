from setuptools import setup, find_packages

setup(
    name="elara-search",
    version="1.0.0",
    description="Minimalistic Multimodal Semantic Search for Windows powered by Google EmbeddingGemma 2",
    author="Elara Team",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "torch>=2.1.0",
        "sentence-transformers>=3.0.0",
        "Pillow>=10.0.0",
        "opencv-python>=4.8.0",
        "soundfile>=0.12.0",
        "pypdf>=4.0.0",
        "numpy>=1.24.0",
        "rich>=13.0.0",
        "pyreadline3>=3.4.0; sys_platform == 'win32'",
    ],
    entry_points={
        "console_scripts": [
            "elara = gemma_search.cli:main",
        ],
    },
)
