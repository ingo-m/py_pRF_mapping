# -*- coding: utf-8 -*-
"""Preprocessing of fMRI data and pRF model time courses."""

# Part of py_pRF_mapping library
# Copyright (C) 2016  Ingo Marquardt
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import numpy as np
import h5py
import threading
import queue
from pyprf.analysis.utilities import load_nii
from pyprf.analysis.preprocessing_par import funcLnTrRm
from nii_to_hdf5 import feed_hdf5
from nii_to_hdf5 import feed_hdf5_spt
from nii_to_hdf5 import feed_hdf5_tme


def pre_pro_func(strPathNiiMask, lstPathNiiFunc, lgcLinTrnd=True,
                 varSdSmthTmp=2.0, varSdSmthSpt=0.0):
    """
    Load & preprocess functional data - hdf5 mode.

    Parameters
    ----------
    strPathNiiMask: str
        Path or mask used to restrict pRF model finding. Only voxels with
        a value greater than zero in the mask are considered.
    lstPathNiiFunc : list
        List of paths of functional data (nii files).
    lgcLinTrnd : bool
        Whether to perform linear trend removal on functional data.
    varSdSmthTmp : float
        Extent of temporal smoothing that is applied to functional data and
        pRF time course models, [SD of Gaussian kernel, in seconds]. If `zero`,
        no temporal smoothing is applied.
     varSdSmthSpt : float
        Extent of spatial smoothing [SD of Gaussian kernel, in mm]. If `zero`,
        no spatial smoothing is applied.
    varPar : int
        Number of processes to run in parallel (multiprocessing).

    Returns
    -------
    aryLgcMsk : np.array
        3D numpy array with logial values. Externally supplied mask (e.g grey
        matter mask). Voxels that are `False` in the mask are excluded.
    hdrMsk : nibabel-header-object
        Nii header of mask.
    aryAff : np.array
        Array containing 'affine', i.e. information about spatial positioning
        of mask nii data.
    aryLgcVar : np.array
        1D numpy array containing logical values. One value per voxel after
        mask has been applied. If `True`, the variance of the voxel's time
        course is larger than zero, and the voxel is included in the output
        array (`aryFunc`). If `False`, the varuance of the voxel's time course
        is zero, and the voxel has been excluded from the output (`aryFunc`).
        This is to avoid problems in the subsequent model fitting. This array
        is necessary to put results into original dimensions after model
        fitting.
    aryFunc : np.array
        2D numpy array containing preprocessed functional data, of the form
        aryFunc[voxelCount, time].
    tplHdf5Shp : tuple
        Spatial dimensions of input nii data (number of voxels in x, y, z
        direction). The data are reshaped during preprocessing, this
        information is needed to fit final output into original spatial
        dimensions.

    Notes
    -----
    Functional data is loaded from disk. Temporal and spatial smoothing can be
    applied. The functional data is reshaped, into the form aryFunc[voxel,
    time]. A mask is applied (externally supplied, e.g. a grey matter mask).
    Subsequently, the functional data is de-meaned, and intensities are
    converted into z-scores.

    """
    print('------Load & preprocess nii data (hdf5 mode)')

    # Load mask (to restrict model fitting):
    aryMask, hdrMsk, aryAff = load_nii(strPathNiiMask)

    # Mask is loaded as float32, but is better represented as integer:
    aryMask = np.array(aryMask).astype(np.int16)

    # Number of non-zero voxels in mask:
    # varNumVoxMsk = int(np.count_nonzero(aryMask))

    # Dimensions of nii data:
    tplNiiShp = aryMask.shape

    # Total number of voxels:
    varNumVox = (tplNiiShp[0] * tplNiiShp[1] * tplNiiShp[2])

    # Number of runs:
    varNumRun = len(lstPathNiiFunc)

    # Loop through runs and load data:
    for idxRun in range(varNumRun):

        print(('---------Preprocess run ' + str(idxRun + 1)))

        # Path of 4D nii file:
        strPthNii = lstPathNiiFunc[idxRun]

        # File path & file name:
        strFlePth, strFleNme = os.path.split(strPthNii)

        # Remove file extension from file name:
        strFleNme = strFleNme.split('.')[0]

        # Path of hdf5 file with functional data (corresponding to 4D nii file
        # for current run).
        strPthHdf5 = os.path.join(strFlePth, (strFleNme + '.hdf5'))

        assert os.path.isfile(strPthHdf5), 'HDF5 file not found.'

        # Read & write file:
        fleHdf5 = h5py.File(strPthHdf5, 'r+')

        # Access dataset in current hdf5 file:
        dtsFunc = fleHdf5['func']

        # Dimensions of hdf5 data (should be of shape func[time, voxel]):
        tplHdf5Shp = dtsFunc.shape

        # Number of time points in hdf5 file:
        varNumVol = tplHdf5Shp[0]

        # Preprocessing of nii data.

        # ---------------------------------------------------------------------
        # Linear trend removal.
        if lgcLinTrnd:

            print('---------Linear trend removal')

            # Looping voxel by voxel is too slow. Instead, read & write a
            # chunks of voxels at a time. Indices of chunks:
            varStpSze = 100
            vecSplt = np.arange(0, (varNumVox + 1), varStpSze)
            vecSplt = np.concatenate((vecSplt, np.array([varNumVox])))

            # Number of chunks:
            varNumCnk = vecSplt.shape[0]

            # Buffer size:
            varBuff = 100

            # Create FIFO queue:
            objQ = queue.Queue(maxsize=varBuff)

            # Define & run extra thread with graph that places data on queue:
            objThrd = threading.Thread(target=feed_hdf5_spt,
                                       args=(dtsFunc, objQ, vecSplt))
            objThrd.setDaemon(True)
            objThrd.start()

            # Loop through chunks of volumes:
            for idxChnk in range((varNumCnk - 1)):

                # Start index of current chunk:
                varIdx01 = vecSplt[idxChnk]

                # Stop index of current chunk:
                varIdx02 = vecSplt[idxChnk + 1]

                # Get chunk of functional data from hdf5 file:
                aryFunc = dtsFunc[:, varIdx01:varIdx02]

                # Perform linear trend removal:
                aryFunc = funcLnTrRm(0, aryFunc, 0.0, None)

                # Put result on queue (from where it will be saved to disk in a
                # separate thread).
                objQ.put(aryFunc)

            # Close thread:
            objThrd.join()

        # ---------------------------------------------------------------------
        # Perform spatial smoothing on fMRI data:
        if 0.0 < varSdSmthSpt:

            print('---------Spatial smoothing')

            # Looping volume by volume is too slow. Instead, read & write a
            # chunk of volumes at a time. Indices of chunks:
            varStpSze = 10
            vecSplt = np.arange(0, (varNumVol + 1), varStpSze)
            vecSplt = np.concatenate((vecSplt, np.array([varNumVol])))

            # Number of chunks:
            varNumCnk = vecSplt.shape[0]

            # Buffer size:
            varBuff = 100

            # Create FIFO queue:
            objQ = queue.Queue(maxsize=varBuff)

            # Define & run extra thread with graph that places data on queue:
            objThrd = threading.Thread(target=feed_hdf5_tme,
                                       args=(dtsFunc, objQ, vecSplt))
            objThrd.setDaemon(True)
            objThrd.start()

            # Loop through chunks of volumes:
            for idxChnk in range((varNumCnk - 1)):

                print(idxChnk)

                # Start index of current chunk:
                varIdx01 = vecSplt[idxChnk]

                # Stop index of current chunk:
                varIdx02 = vecSplt[idxChnk + 1]

                # Number of volumes in current chunk:
                varNumVolTmp = varIdx02 - varIdx01

                # Get chunk of functional data from hdf5 file:
                aryFunc = dtsFunc[varIdx01:varIdx02, :]

                # Loop through volumes (within current chunk):
                varChnkNumVol = aryFunc.shape[0]
                for idxVol in range(varChnkNumVol):

                    # Reshape into original shape (for spatial smoothing):
                    aryTmp = aryFunc[idxVol, :].reshape(tplNiiShp)

                    # Perform smoothing:
                    aryTmp = gaussian_filter(
                        aryTmp,
                        varSdSmthSpt,
                        order=0,
                        mode='nearest',
                        truncate=4.0)

                    # Back to shape: func[time, voxel].
                    aryFunc[idxVol, :] = aryTmp.reshape(1, varNumVox)

                # Put current volume on queue.
                objQ.put(aryFunc)

            # Close thread:
            objThrd.join()

        # ---------------------------------------------------------------------
        # Apply mask

        # Path of hdf5 file for masked functional data:
        strPthHdf5Msk = os.path.join(strFlePth, (strFleNme + '_masked.hdf5'))

        # Reshape mask:
        aryMask = aryMask.reshape(varNumVox)

        # Make mask boolean:
        aryLgcMsk = np.greater(aryMask.astype(np.int16),
                               np.array([0], dtype=np.int16)[0])

        # Number of voxels after masking:
        varNumVoxMsk = np.sum(aryLgcMsk)

        # Create hdf5 file:
        fleHdf5Msk = h5py.File(strPthHdf5Msk, 'w')

        # Create dataset within hdf5 file:
        dtsFuncMsk = fleHdf5.create_dataset('func',
                                            (varNumVol, varNumVoxMsk),
                                            dtype=np.float32)

        # Buffer size:
        varBuff = 100

        # Create FIFO queue:
        objQ = queue.Queue(maxsize=varBuff)

        # Define & run extra thread with graph that places data on queue:
        objThrd = threading.Thread(target=feed_hdf5,
                                   args=(dtsFuncMsk, objQ, varNumVox))
        objThrd.setDaemon(True)
        objThrd.start()

        # Loop through voxel and place voxel time courses that are within the
        # mask in new hdf5 file:
        for idxVox in range(varNumVox):
            if aryLgcMsk[idxVox]:
                objQ.put(dtsFunc[:, idxVox])

        # Close thread:
        objThrd.join()

        # Close hdf5 files:
        fleHdf5.close()
        fleHdf5Msk.close()

        # ---------------------------------------------------------------------
        # Perform temporal smoothing:

        # Read & write file (after masking):
        fleHdf5Msk = h5py.File(strPthHdf5Msk, 'r+')

        # Access dataset in current hdf5 file:
        dtsFunc = fleHdf5Msk['func']

        if 0.0 < varSdSmthTmp:

            print('---------Temporal smoothing')

            # Looping voxel by voxel is too slow. Instead, read & write a
            # chunks of voxels at a time. Indices of chunks:
            varStpSze = 100
            vecSplt = np.arange(0, (varNumVox + 1), varStpSze)
            vecSplt = np.concatenate((vecSplt, np.array([varNumVox])))

            # Number of chunks:
            varNumCnk = vecSplt.shape[0]

            # Buffer size:
            varBuff = 100

            # Create FIFO queue:
            objQ = queue.Queue(maxsize=varBuff)

            # Define & run extra thread with graph that places data on queue:
            objThrd = threading.Thread(target=feed_hdf5_spt,
                                       args=(dtsFunc, objQ, vecSplt))
            objThrd.setDaemon(True)
            objThrd.start()

            # Loop through chunks of volumes:
            for idxChnk in range((varNumCnk - 1)):

                # Start index of current chunk:
                varIdx01 = vecSplt[idxChnk]

                # Stop index of current chunk:
                varIdx02 = vecSplt[idxChnk + 1]

                # Get chunk of functional data from hdf5 file:
                aryFunc = dtsFunc[:, varIdx01:varIdx02]

                # Perform temporal smoothing:
                aryFunc = funcSmthTmp(0, aryFunc, varSdSmthTmp, None)

                # Put result on queue (from where it will be saved to disk in a
                # separate thread).
                objQ.put(aryFunc)

            # Close thread:
            objThrd.join()










        # De-mean functional data:
        aryTmpFunc = np.subtract(aryTmpFunc,
                                 np.mean(aryTmpFunc,
                                         axis=1,
                                         dtype=np.float32)[:, None])

        # Convert intensities into z-scores. If there are several pRF runs,
        # these are concatenated. Z-scoring ensures that differences in mean
        # image intensity and/or variance between runs do not confound the
        # analysis. Possible enhancement: Explicitly model across-runs variance
        # with a nuisance regressor in the GLM.
        aryTmpStd = np.std(aryTmpFunc, axis=1)

        # In order to avoid devision by zero, only divide those voxels with a
        # standard deviation greater than zero:
        aryTmpLgc = np.greater(aryTmpStd.astype(np.float32),
                               np.array([0.0], dtype=np.float32)[0])
        # Z-scoring:
        aryTmpFunc[aryTmpLgc, :] = np.divide(aryTmpFunc[aryTmpLgc, :],
                                             aryTmpStd[aryTmpLgc, None])
        # Set voxels with a variance of zero to intensity zero:
        aryTmpLgc = np.not_equal(aryTmpLgc, True)
        aryTmpFunc[aryTmpLgc, :] = np.array([0.0], dtype=np.float32)[0]

        # Put preprocessed functional data of current run into list:
        lstFunc.append(aryTmpFunc)
        del(aryTmpFunc)

+++
        # Close thread:
        objThrd.join()

        # Close hdf5 file:
        fleHdf5.close()
+++

    # Put functional data from separate runs into one array. 2D array of the
    # form aryFunc[voxelCount, time]
    aryFunc = np.concatenate(lstFunc, axis=1).astype(np.float32, copy=False)
    del(lstFunc)

    # Voxels that are outside the brain and have no, or very little, signal
    # should not be included in the pRF model finding. We take the variance
    # over time and exclude voxels with a suspiciously low variance. Because
    # the data given into the cython or GPU function has float32 precision, we
    # calculate the variance on data with float32 precision.
    aryFuncVar = np.var(aryFunc, axis=1, dtype=np.float32)

    # Is the variance greater than zero?
    aryLgcVar = np.greater(aryFuncVar,
                           np.array([0.0001]).astype(np.float32)[0])

    # Array with functional data for which conditions (mask inclusion and
    # cutoff value) are fullfilled:
    aryFunc = aryFunc[aryLgcVar, :]

    return aryLgcMsk, hdrMsk, aryAff, aryLgcVar, aryFunc, tplHdf5Shp


def pre_pro_models(aryPrfTc, varSdSmthTmp=2.0, varPar=10, strPathMdl=None):
    """
    Preprocess pRF model time courses - hdf5 mode.

    Parameters
    ----------
    aryPrfTc : np.array or None
        Array with pRF time course models, shape:
        aryPrfTc[x-position, y-position, SD, condition, volume]. If `None`
        (hdf5-mode, i.e. large parameter space), pRF model time courses are
        loaded from & saved to hdf5 file.
    varSdSmthTmp : float
        Extent of temporal smoothing that is applied to functional data and
        pRF time course models, [SD of Gaussian kernel, in seconds]. If `zero`,
        no temporal smoothing is applied.
    varPar : int
        Number of processes to run in parallel (multiprocessing).
    strPathMdl : str or None
        Path of file with pRF time course models (without file extension). In
        hdf5 mode, time courses are loaded to & saved to hdf5 file, so that
        not all pRF model time courses do not have to be loaded into RAM at
        once.

    Returns
    -------
    aryPrfTc : np.array
        Array with preprocessed pRF time course models, same shape as input
        (aryPrfTc[x-position, y-position, SD, condition, volume]).

    Notes
    -----
    Only temporal smoothing is applied to the pRF model time courses.

    """
    print('------Preprocess pRF time course models')

    # Hdf5 mode?
    if aryPrfTc is None:

        # Path of hdf5 file:
        strPthHdf5 = (strPathMdl + '.hdf5')

        # Read file:
        fleHdf5 = h5py.File(strPthHdf5, 'r+')

        # Access dataset in current hdf5 file:
        aryPrfTc = fleHdf5['pRF_time_courses']

    # Loop through stimulus conditions, because the array needs to the 4D,
    # with time as last dimension, for the preprocessing. Otherwise the
    # same functions could not be used for the functional data and model
    # time courses (which would increase redundancy).
    varNumCon = aryPrfTc.shape[3]
    for idxCon in range(varNumCon):

        # Preprocessing of pRF time course models:
        aryPrfTc[:, :, :, idxCon, :] = pre_pro_par(
            aryPrfTc[:, :, :, idxCon, :], aryMask=np.array([]),
            lgcLinTrnd=False, varSdSmthTmp=varSdSmthTmp, varSdSmthSpt=0.0,
            varPar=varPar)

    # Hdf5 mode?
    if aryPrfTc is None:

        # Dummy pRF time course array:
        aryPrfTc = None

        # Close hdf5 file:
        fleHdf5.close()

    return aryPrfTc
