import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="tistel",
    version="0.5.2",
    author="nycz",
    description="image viewer/organizer",
    install_requires=['PyQt5', 'libsyntyche', 'jfti'],
    include_package_data=True,
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages(),
    entry_points={
        'gui_scripts': [
            'tistel=tistel.tistel:main'
        ]
    },
)
