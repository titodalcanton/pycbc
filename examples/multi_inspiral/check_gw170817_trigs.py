#!/usr/bin/env python
# Read a pycbc_multi_inspiral HDF5 trigger file and check that it contains
# triggers compatible with mock GW170817-like injections
# 2022 Andrew Williamson, Tito Dal Canton

import sys
import logging
import h5py
from pycbc import init_logging


init_logging(True)

gw170817_time = 1187008882.43

with h5py.File('GW170817_test_output.hdf', 'r') as f:
    end_time = f['network/end_time_gc'][:]
    coherent_snr = f['network/coherent_snr'][:]
    reweighted_snr = f['network/reweighted_snr'][:]
    slide_id = f['network/slide_id'][:]

# search for compatible trigs
mask = (
    (abs(gw170817_time - end_time) < 0.1)
    & (coherent_snr > 25)
    & (reweighted_snr > 25)
    & (slide_id == 0)
)
num_trigs = mask.sum()
if num_trigs > 0:
    logging.info(
        'PASS: GW170817 found with coherent SNR %.2f, reweighted SNR %.2f',
        coherent_snr[mask],
        reweighted_snr[mask]
    )
else:
    logging.error('FAIL: GW170817 missed')
    sys.exit(1)
