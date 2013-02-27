'''
Collection of tests for orbital correction.

Created on 31/3/13
@author: Ben Davies
'''


import unittest
from glob import glob
from os.path import join
from numpy import nan, isnan, array, reshape, ones, zeros, float32, meshgrid
from numpy.testing import assert_array_equal, assert_array_almost_equal

import algorithm
from shared import Ifg
from orbital import OrbitalCorrectionError
from orbital import orbital_correction, get_design_matrix, get_network_design_matrix
from orbital import INDEPENDENT_METHOD, NETWORK_METHOD, PLANAR, QUADRATIC
from algorithm_tests import MockIfg, sydney_test_setup



class OrbitalTests(unittest.TestCase):
	'''Test cases for the orbital correction component of PyRate.'''

	def setUp(self):
		xstep, ystep = 0.6, 0.7  # fake cell sizes

		shape = (6, 2)
		designm = zeros(shape) # planar design matrix for 2x3 orig array
		designm[0] = [0, 0]
		designm[1] = [0, xstep]
		designm[2] = [ystep, 0]
		designm[3] = [ystep, xstep]
		designm[4] = [2*ystep, 0]
		designm[5] = [2*ystep, xstep]

		self.designm = designm
		self.xstep = xstep
		self.ystep = ystep


	def test_design_matrix_planar(self):
		_, ifgs = sydney_test_setup()

		xs, ys = 2, 3
		m = MockIfg(ifgs[0], xs, ys)
		m.X_STEP = self.xstep
		m.Y_STEP = self.ystep

		# no offsets
		design_mat = get_design_matrix(m, PLANAR, False)
		assert_array_almost_equal(design_mat, self.designm)

		# with offset
		design_mat = get_design_matrix(m, PLANAR, True)
		nys, nxs = self.designm.shape
		nxs += 1 # for offset col
		exp = ones((nys,nxs), dtype=float32)
		exp[:,:2] = self.designm
		assert_array_almost_equal(design_mat, exp)


	def test_design_matrix_quadratic(self):
		dm = []
		ys, xs = (3, 5)
		for y in xrange(ys):
			for x in xrange(xs):
				dm.append([(x * self.xstep)**2,
									(y * self.ystep)**2,
									(x * self.xstep) * (y * self.ystep),
									x * self.xstep,
									y * self.ystep])

		exp_dm = array(dm, dtype=float32) # planar design matrix

		# get design matrix from an ifg
		ifg = Ifg("../../tests/sydney_test/obs/geo_060619-061002.unw")
		ifg.open()
		m = MockIfg(ifg, xs, ys)
		m.X_STEP = self.xstep
		m.Y_STEP = self.ystep

		# no offset
		design_mat = get_design_matrix(m, QUADRATIC, False)
		assert_array_almost_equal(design_mat, exp_dm, decimal=3)

		# with offset
		design_mat = get_design_matrix(m, QUADRATIC, True)
		nys, nxs = exp_dm.shape
		nxs += 1 # for offset col
		exp2 = ones((nys,nxs), dtype=float32)
		exp2[:,:5] = exp_dm
		assert_array_almost_equal(design_mat, exp2, decimal=3)


	def test_ifg_to_vector(self):
		# test numpy reshaping order
		ifg = zeros((2, 3), dtype=float32)
		a = [24, 48, 1000]
		b = [552, 42, 68]
		ifg[0] = a
		ifg[1] = b
		res = reshape(ifg, (len(a+b)))
		exp = array(a + b)
		assert_array_equal(exp, res)

		# ensure order is maintained when converting back
		tmp = reshape(res, ifg.shape)
		assert_array_equal(tmp, ifg)


	def test_orbital_correction(self):
		# verify top level orbital correction function

		def test_results():
			for i, c in zip(ifgs, corrections):
				# are corrections same size as the original array?
				ys, xs = c.shape
				self.assertEqual(i.FILE_LENGTH, ys)
				self.assertEqual(i.WIDTH, xs)
				self.assertFalse(isnan(i.phase_data).all())
				self.assertFalse(isnan(c).all())
				self.assertTrue(c.ptp() != 0) # ensure range of values in grid
				# TODO: do the results need to be checked at all?

		_, ifgs = sydney_test_setup()[:5] # TODO: replace with faked ifglist?
		ifgs[0].phase_data[1, 1:3] = nan # add some NODATA

		# test both models with no offsets
		corrections = orbital_correction(ifgs, PLANAR, INDEPENDENT_METHOD, False)
		test_results()
		corrections = orbital_correction(ifgs, QUADRATIC, INDEPENDENT_METHOD, False)
		test_results()

		# test both with offsets
		corrections = orbital_correction(ifgs, PLANAR, INDEPENDENT_METHOD)
		test_results()
		corrections = orbital_correction(ifgs, QUADRATIC, INDEPENDENT_METHOD)
		test_results()


class OrbitalCorrectionNetwork(unittest.TestCase):
	'''TODO'''

	def setUp(self):
		base = "../../tests/sydney_test/obs"
		self.ifgs = [Ifg(join(base, p)) for p in IFMS5.split()]

	# TODO: check DM/correction with NaN rows

	def test_invalid_ifgs_arg(self):
		args = (PLANAR, True) # some default args
		self.assertRaises(OrbitalCorrectionError, get_network_design_matrix, [], *args)
		self.assertRaises(OrbitalCorrectionError, get_network_design_matrix, [None], *args)
		# TODO: what is the minimum required? 2 ifgs/3 epochs?)


	def test_invalid_degree_arg(self):
		oex = OrbitalCorrectionError
		ifgs = [None] * 5

		for deg in range(-5,1):
			self.assertRaises(oex, get_network_design_matrix, ifgs, deg, True)
		for deg in range(3,6):
			self.assertRaises(oex, get_network_design_matrix, [None], deg, True)


	def test_design_matrix_shape(self):
		# verify shape of design matrix is correct
		num_ifgs = len(self.ifgs)
		num_epochs = num_ifgs + 1
		num_params = 2 # without offsets 1st

		# without offsets
		head = self.ifgs[0]
		exp_num_rows = head.FILE_LENGTH * head.WIDTH * num_ifgs
		exp_num_cols = num_epochs * num_params
		exp_shape = (exp_num_rows, exp_num_cols)
		act_dm = get_network_design_matrix(self.ifgs, PLANAR, False)
		self.assertEqual(exp_shape, act_dm.shape)

		# with offsets
		num_params += 1
		exp_num_cols = num_epochs * num_params
		exp_shape = (exp_num_rows, exp_num_cols)
		act_dm = get_network_design_matrix(self.ifgs, PLANAR, True)
		self.assertEqual(exp_shape, act_dm.shape)

		# quadratic method without offsets
		num_params = 5 # without offsets
		exp_num_cols = num_epochs * num_params
		exp_shape = (exp_num_rows, exp_num_cols)
		act_dm = get_network_design_matrix(self.ifgs, QUADRATIC, False)
		self.assertEqual(exp_shape, act_dm.shape)

		# with offsets
		num_params += 1
		exp_num_cols = num_epochs * num_params
		exp_shape = (exp_num_rows, exp_num_cols)
		act_dm = get_network_design_matrix(self.ifgs, QUADRATIC, True)
		self.assertEqual(exp_shape, act_dm.shape)


	def test_planar_matrix_content(self):
		# verify creation of sparse matrix comprised of smaller design matricies
		# TODO: do master/slave indices need to be sorted? Sorted = less ambiguity

		dates = []
		for ifg in self.ifgs:
			dates += list(ifg.DATE12)
		date_ids = algorithm.master_slave_ids(dates)
		ncoef = 2 # planar without offsets

		for offset in [False, True]:
			if offset: ncoef += 1
			act_dm = get_network_design_matrix(self.ifgs, PLANAR, offset)
			self.assertNotEqual(act_dm.ptp(), 0)

			for i, ifg in enumerate(self.ifgs):
				exp_dm = unittest_dm(ifg, ifg.X_STEP, ifg.Y_STEP, PLANAR, offset)

				# use slightly refactored version of Hua's code to test
				ib1 = i * ifg.num_cells # start row for subsetting the sparse matrix
				ib2 = (i+1) * ifg.num_cells # last row of subset of sparse matrix
				jbm = date_ids[ifg.MASTER] * ncoef # starting row index for master
				jbs = date_ids[ifg.SLAVE] * ncoef # row start for slave
				assert_array_almost_equal(-exp_dm, act_dm[ib1:ib2, jbm:jbm+ncoef])
				assert_array_almost_equal(exp_dm, act_dm[ib1:ib2, jbs:jbs+ncoef])


# FIXME: add derived field to ifgs to convert X|Y_STEP degrees to metres
def unittest_dm(ifg, xs, ys, degree, offset=False):
	ncoef = 2 if degree == PLANAR else 5
	if offset is True:
		ncoef += 1

	out = ones((ifg.num_cells, ncoef), dtype=float32)
	X, Y = meshgrid(range(ifg.WIDTH), range(ifg.FILE_LENGTH))
	X = X.reshape(ifg.num_cells) * xs
	Y = Y.reshape(ifg.num_cells) * ys

	if degree == PLANAR:
		out[:,0] = Y
		out[:,1] = X
	elif degree == QUADRATIC:
		out[:,0] = Y**2
		out[:,1] = X**2
		out[:,2] = X * Y
		out[:,3] = Y
		out[:,4] = X
	else:
		raise Exception("Degree is invalid")

	return out


	# TODO:
	#def test_network_design_matrix_quadratic(self):
		#pass


# small dummy ifg list to limit # of ifgs
IFMS5 = """geo_060828-061211.unw
geo_061106-061211.unw
geo_061106-070115.unw
geo_061106-070326.unw
geo_070326-070917.unw
"""
