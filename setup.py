"""
pyprf setup.

For development installation:
    pip install -e /path/to/pRF_mapping
"""

from setuptools import setup, Extension
from Cython.Build import cythonize
import numpy

extensions = [Extension("pyprf.analysis.cython_leastsquares",
                        ["pyprf/analysis/cython_leastsquares.pyx"],
                        include_dirs=[numpy.get_include()])]

with open('README.md') as f:
    long_description = f.read()

setup(name='pyprf',
      version='1.1.1',
      description=('A free & open source python tool for population receptive \
                    field analysis of fMRI data.'),
      url='https://github.com/ingo-m/pyprf',
      author='Ingo Marquardt',
      license='GNU General Public License Version 3',
      packages=['pyprf.analysis'],
      install_requires=['numpy', 'scipy', 'nibabel', 'pillow', 'cython',
                        'tensorflow'],
      keywords=['pRF', 'fMRI', 'retinotopy'],
      long_description=long_description,
      setup_requires=['cython', 'numpy'],
      ext_modules=cythonize(extensions),
      entry_points={
          'console_scripts': [
              'pyprf = pyprf.analysis.__main__:main',
              ]},
      )
