"""Unit tests for function minimization using conjugate gradients."""

# Copyright 2011 Matt Shannon

# This file is part of armspeech.
# See `License` for details of license and warranty.


from __future__ import division

from minimize import checkGrad, solveToMinimize, solveByMinimize, minimize

import unittest
import math
from numpy import *
from numpy.random import randn, randint
import numpy.linalg as la

# FIXME : add tests for other minimize.py stuff (some manual tests currently exist in other files?)

def id(x):
    s = shape(x)
    if len(s) == 0:
        return x, 1.0
    elif len(s) == 1:
        return x, eye(len(x))
    else:
        raise RuntimeError('function called on tensor of rank >= 2')

def cubic1D(x):
    assert len(shape(x)) == 0
    return x * x * x + x, array([3 * x * x + 1])

def cubic(x):
    assert len(shape(x)) == 1
    return x * x * x + x, array([3 * x * x + 1])

class TestMinimize(unittest.TestCase):
    def test_solveToMinimize(self, its = 100, numPoints = 10):
        for it in range(its):
            dim = randint(0, 10)
            a = randn(dim)
            checkGrad(solveToMinimize(id, a), dim, numPoints = numPoints)
        for it in range(its):
            x0 = randn()
            a = randn()
            checkGrad(solveToMinimize(cubic1D, a, convertFrom1D = True), 1, numPoints = numPoints)
        for it in range(its):
            x0 = randn(1)
            a = randn(1)
            checkGrad(solveToMinimize(cubic, a), 1, numPoints = numPoints)
    def test_solveByMinimize(self, length = -100, its = 100):
        def checkSolve(f, a, x0):
            sol = solveByMinimize(f, a, x0, length = length)
            self.assertAlmostEqual(la.norm(f(sol)[0] - a), 0.0)
        for it in range(its):
            dim = randint(0, 10)
            x0 = randn(dim)
            a = randn(dim)
            checkSolve(id, a, x0)
        for it in range(its):
            x0 = randn()
            a = randn()
            checkSolve(cubic1D, a, x0)
        for it in range(its):
            x0 = randn(1)
            a = randn(1)
            checkSolve(cubic, a, x0)

def suite():
    return unittest.TestLoader().loadTestsFromTestCase(TestMinimize)

if __name__ == '__main__':
    unittest.main()
