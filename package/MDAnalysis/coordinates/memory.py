# -*- Mode: python; tab-width: 4; indent-tabs-mode:nil; coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
#
# MDAnalysis --- http://www.MDAnalysis.org
# Copyright (c) 2006-2015 Naveen Michaud-Agrawal, Elizabeth J. Denning, Oliver Beckstein
# and contributors (see AUTHORS for the full list)
#
# Released under the GNU Public Licence, v2 or any higher version
#
# Please cite your use of MDAnalysis in published work:
#
# N. Michaud-Agrawal, E. J. Denning, T. B. Woolf, and O. Beckstein.
# MDAnalysis: A Toolkit for the Analysis of Molecular Dynamics Simulations.
# J. Comput. Chem. 32 (2011), 2319--2327, doi:10.1002/jcc.21787
#
"""
Reading trajectories from memory --- :mod:`MDAnalysis.coordinates.memory`
==========================================================================

:Author: Wouter Boomsma
:Year: 2016
:Copyright: GNU Public License v2
:Maintainer: Wouter Boomsma <wb@bio.ku.dk>, wouterboomsma on github


.. versionadded:: 0.14.0

The module contains a trajectory reader that operates on an array
in memory, rather than reading from file. This makes it possible to
use operate on raw coordinate using existing MDAnalysis tools. In
addition, it allows the user to make changes to the coordinates in
a trajectory (e.g. through AtomGroup.set_positions) without having
to write the entire state to file.


Examples
--------

Constructing a Reader from a numpy array
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A simple example where a new universe is created from the
array extracted from a DCD timeseries

    from MDAnalysis import Universe
    from MDAnalysisTests.datafiles import DCD, PDB_small
    from MDAnalysis.coordinates.array import ArrayReader

    universe = Universe(PDB_small, DCD)
    coordinates = universe.trajectory.timeseries(universe.atoms)

    universe2 = Universe(PDB_small, coordinates,
                         format=MemoryReader)

This two step process can also be done in one go:

    universe = Universe(PDB_small, DCD, in_memory=True)

"""

import errno
import numpy as np

from . import base


class MemoryReader(base.ProtoReader):
    """
    A trajectory reader interface to a numpy array of the coordinates.
    For compatibility with the timeseries interface, support is provided for
    specifying the order of columns through the format option.

    Parameter
    ---------
    filename : str
        filename of the trajectory
    n_atoms : int
        number of atoms to write
    convert_units : bool (optional)
        convert into MDAnalysis units
    precision : float (optional)
        set precision of saved trajectory to this number of decimal places.
    """

    format = 'memory'

    class MemoryTimestep(base.Timestep):
        """
        Overrides the positions property in base.Timestep to
        use avoid duplication of the array.
        """

        @property
        def positions(self):
            return base.Timestep.positions.fget(self)

        @positions.setter
        def positions(self, new):
            self.has_positions = True
            # Use reference to original rather than a copy
            self._pos = new

    _Timestep = MemoryTimestep

    def __init__(self, coordinate_array, format='afc',
                 dimensions = None, dt=1, **kwargs):
        """Constructor

        Parameters
        ---------
        coordinate_array : :class:`~numpy.ndarray object
            The underlying array of coordinates
        format : str
            the order/shape of the return data array, corresponding
            to (a)tom, (f)rame, (c)oordinates all six combinations
            of 'a', 'f', 'c' are allowed ie "fac" - return array
            where the shape is (frame, number of atoms,
            coordinates)
        """
        self.set_array(np.asarray(coordinate_array), format)
        self.n_frames = self.coordinate_array.shape[self.format.find('f')]
        self.n_atoms = self.coordinate_array.shape[self.format.find('a')]

        kwargs.pop("n_atoms", None)
        self.ts = self._Timestep(self.n_atoms, **kwargs)
        self.ts.dt = dt
        if dimensions is not None:
            self.ts.dimensions = dimensions
        # self.ts.frame = -1
        self._read_next_timestep()

    def set_array(self, coordinate_array, format='afc'):
        """
        Set underlying array in desired column format.

        Parameters
        ---------
        coordinate_array : :class:`~numpy.ndarray object
            The underlying array of coordinates
        format
            The order/shape of the return data array, corresponding
            to (a)tom, (f)rame, (c)oordinates all six combinations
            of 'a', 'f', 'c' are allowed ie "fac" - return array
            where the shape is (frame, number of atoms,
            coordinates)
        """
        self.coordinate_array = coordinate_array
        self.format = format

    def get_array(self):
        """
        Return underlying array.
        """
        return self.coordinate_array

    def _reopen(self):
        """Reset iteration to first frame"""
        self.ts.frame = -1

    def timeseries(self, asel=None, start=0, stop=-1, skip=1, format='afc'):
        """Return a subset of coordinate data for an AtomGroup in desired
        column format. If no selection is given, it will return a view of
        the underlying array, while a copy is returned otherwise.

        Parameters
        ---------
        asel : :class:`~MDAnalysis.core.AtomGroup.AtomGroup` object
            Atom selection
        start, stop, skip : int
            range of trajectory to access, start and stop are inclusive
        format : str
            the order/shape of the return data array, corresponding
            to (a)tom, (f)rame, (c)oordinates all six combinations
            of 'a', 'f', 'c' are allowed ie "fac" - return array
            where the shape is (frame, number of atoms,
            coordinates)
        """
        array = self.get_array()
        if format == self.format:
            pass
        elif format[0] == self.format[0]:
            array = np.swapaxes(array, 1, 2)
        elif format[1] == self.format[1]:
            array = np.swapaxes(array, 0, 2)
        elif format[2] == self.format[2]:
            array = np.swapaxes(array, 0, 1)
        elif self.format[1] == format[0]:
            array = np.swapaxes(array, 1, 0)
            array = np.swapaxes(array, 1, 2)
        elif self.format[2] == format[0]:
            array = np.swapaxes(array, 2, 0)
            array = np.swapaxes(array, 1, 2)

        a_index = format.find('a')
        f_index = format.find('f')
        stop_index = stop+1
        if stop_index == 0:
            stop_index = None
        # To make the skip implementation consistent with DCD.timeseries, we
        # start at start+(skip-1)
        basic_slice = ([slice(None)]*(f_index) +
                       [slice(start+(skip-1), stop_index, skip)] +
                       [slice(None)]*(2-f_index))

        # Return a view if either:
        #   1) asel is None
        #   2) asel corresponds to a selection of all atoms. To avoid doing
        #      a full comparison of all atom objects in the selection, we check
        #      for the length and the identity of the first atom.
        array = array[basic_slice]
        if (asel is None or
            (len(asel) == len(asel.universe.atoms) and
             asel[0] is asel.universe.atoms[0])):
            return array
        else:
            # If selection is specified, return a copy
            return array.take(asel.indices, a_index)

    def _read_next_timestep(self, ts=None):
        """copy next frame into timestep"""

        if self.ts.frame >= self.n_frames-1:
            raise IOError(errno.EIO, 'trying to go over trajectory limit')
        if ts is None:
            ts = self.ts
        ts.frame += 1
        f_index = self.format.find('f')
        basic_slice = ([slice(None)]*(f_index) +
                       [self.ts.frame] +
                       [slice(None)]*(2-f_index))
        ts.positions = self.coordinate_array[basic_slice]

        ts.time = self.ts.frame*self.dt
        return ts

    def _read_frame(self, i):
        """read frame i"""
        self.ts.frame = i-1
        return self._read_next_timestep()

    def __repr__(self):
        """String representation"""
        return ("<{cls} with {nframes} frames of {natoms} atoms>"
                "".format(
                    cls=self.__class__.__name__,
                    nframes=self.n_frames,
                    natoms=self.n_atoms
                ))
