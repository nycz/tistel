import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="tistel",
    version="0.0.1",
    author="nycz",
    description="image viewer/organizer",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages(),
    entry_points={
        'gui_scripts': [
            'tistel=tistel.tistel:main'
        ]
    },
)
