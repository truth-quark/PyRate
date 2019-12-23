#   This Python module is part of the PyRate software package.
#
#   Copyright 2020 Geoscience Australia
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
"""
This Python module implements pixel-by-pixel linear rate
(velocity) estimation using an iterative weighted least-squares
stacking method.
"""
import itertools

from scipy.linalg import solve, cholesky, qr, inv
from numpy import nan, isnan, sqrt, diag, delete, array, float32
import numpy as np
from joblib import Parallel, delayed
from core import config as cf
from core.shared import joblib_log_level


def stack_rate(ifgs, params, vcmt, mst=None):
    """
    Pixel-by-pixel linear rate (velocity) estimation using iterative
    weighted least-squares stacking method.

    :param Ifg.object ifgs: Sequence of interferogram objects from which to extract observations
    :param dict params: Configuration parameters
    :param ndarray vcmt: Derived positive definite temporal variance covariance matrix
    :param ndarray mst: Pixel-wise matrix describing the minimum spanning tree network

    :return: rate: Linear rate (velocity) map
    :rtype: ndarray
    :return: error: Standard deviation of the rate map
    :rtype: ndarray
    :return: samples: Statistics of observations used in calculation
    :rtype: ndarray
    """
    maxsig, nsig, pthresh, cols, error, mst, obs, parallel, _, rate, rows, samples, span = _stack_setup(ifgs, mst, params)

    # pixel-by-pixel calculation.
    # nested loops to loop over the 2 image dimensions
    if parallel == 1:

        res = Parallel(n_jobs=params[cf.PROCESSES], verbose=joblib_log_level(cf.LOG_LEVEL))(
            delayed(_stack_rate_by_rows)(r, cols, mst, nsig, obs, pthresh, span, vcmt) for r in range(rows)
        )
        res = np.array(res)
        rate = res[:, :, 0]
        error = res[:, :, 1]
        samples = res[:, :, 2]
    elif parallel == 2:
        res = Parallel(n_jobs=params[cf.PROCESSES], verbose=joblib_log_level(cf.LOG_LEVEL))(
            delayed(_stack_rate_by_pixel)(r, c, mst, nsig, obs, pthresh, span, vcmt) for r, c in itertools.product(range(rows), range(cols))
        )
        res = np.array(res)

        rate = res[:, 0].reshape(rows, cols)
        error = res[:, 1].reshape(rows, cols)
        samples = res[:, 2].reshape(rows, cols)
    else:
        for i in range(rows):
            for j in range(cols):
                rate[i, j], error[i, j], samples[i, j] = _stack_rate_by_pixel(i, j, mst, nsig, obs, pthresh, span, vcmt)

    # overwrite the data whose error is larger than the
    # maximum sigma user threshold
    mask = ~isnan(error)
    mask[mask] &= error[mask] > maxsig
    rate[mask] = nan
    error[mask] = nan
    # samples[mask] = nan # should we also mask the samples?

    return rate, error, samples


def _stack_setup(ifgs, mst, params):
    """
    Convenience function for stack rate setup
    """
    # MULTIPROCESSING parameters
    parallel = params[cf.PARALLEL]
    processes = params[cf.PROCESSES]
    # stack rate parameters from config file
    # n-sigma ratio used to threshold 'model minus observation' residuals
    nsig = params[cf.LR_NSIG]
    # Threshold for maximum allowable standard error
    maxsig = params[cf.LR_MAXSIG]
    # Pixel threshold; minimum number of coherent observations for a pixel
    pthresh = params[cf.LR_PTHRESH]
    rows, cols = ifgs[0].phase_data.shape
    # make 3D block of observations
    obs = array([np.where(isnan(x.phase_data), 0, x.phase_data) for x in ifgs])
    span = array([[x.time_span for x in ifgs]])
    # Update MST in case additional NaNs generated by APS filtering
    if mst is None:  # dummy mst if none is passed in
        mst = ~isnan(obs)
    else:
        mst[isnan(obs)] = 0

    # preallocate empty arrays. No need to preallocation NaNs with new code
    error = np.empty([rows, cols], dtype=float32)
    rate = np.empty([rows, cols], dtype=float32)
    samples = np.empty([rows, cols], dtype=np.float32)
    return maxsig, nsig, pthresh, cols, error, mst, obs, parallel, processes, rate, rows, samples, span


def _stack_rate_by_rows(row, cols, mst, nsig, obs, pthresh, span, vcmt):
    """helper function for parallel 'row' stack rate computation runs"""

    res = np.empty(shape=(cols, 3), dtype=np.float32)
    for col in range(cols):
        res[col, :] = _stack_rate_by_pixel(row, col, mst, nsig, obs, pthresh, span, vcmt)

    return res


def _stack_rate_by_pixel(row, col, mst, nsig, obs, pthresh, span, vcmt):
    """helper function for computing stack rate for one pixel"""

    # find the indices of independent ifgs for given pixel from MST
    ind = np.nonzero(mst[:, row, col])[0]  # only True's in mst are chosen
    # iterative loop to calculate 'robust' velocity for pixel
    default_no_samples = len(ind)

    while len(ind) >= pthresh:
        # make vector of selected ifg observations
        ifgv = obs[ind, row, col]

        # form design matrix from appropriate ifg time spans
        B = span[:, ind]

        # Subset of full VCM matrix for selected observations
        vcm_temp = vcmt[ind, np.vstack(ind)]

        # Get the lower triangle cholesky decomposition.
        # V must be positive definite (symmetrical and square)
        T = cholesky(vcm_temp, 1)

        # Incorporate inverse of VCM into the design matrix
        # and observations vector
        A = solve(T, B.transpose())
        b = solve(T, ifgv.transpose())

        # Factor the design matrix, incorporate covariances or weights into the
        # system of equations, and transform the response vector.
        Q, R, _ = qr(A, mode='economic', pivoting=True)
        z = Q.conj().transpose().dot(b)

        # Compute the Lstsq coefficient for the velocity
        v = solve(R, z)

        # Compute the model errors
        err1 = inv(vcm_temp).dot(B.conj().transpose())
        err2 = B.dot(err1)
        err = sqrt(diag(inv(err2)))

        # Compute the residuals (model minus observations)
        r = (B * v) - ifgv

        # determine the ratio of residuals and apriori variances
        w = cholesky(inv(vcm_temp))
        wr = abs(np.dot(w, r.transpose()))

        # test if maximum ratio is greater than user threshold.
        max_val = wr.max()
        if max_val > nsig:
            # if yes, discard and re-do the calculation.
            ind = delete(ind, wr.argmax())
        else:
            # if no, save estimate, exit the while loop and go to next pixel
            return v[0], err[0], ifgv.shape[0]
    # dummy return for no change
    return np.nan, np.nan, default_no_samples
