#!/bin/bash
module purge
module load python3/3.7.4
module load gdal/3.0.2
module load openmpi/2.1.6
export PYTHONPATH=/apps/gdal/3.0.2/lib64/python3.7/site-packages:$PYTHONPAT
source ~/PyRateVenv/bin/activate
pip install -U pytest
cd ~/PyRate
pytest tests/test_algorithm