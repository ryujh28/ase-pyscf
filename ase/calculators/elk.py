import os
from pathlib import Path

import numpy as np

from ase.units import Bohr, Hartree
from ase.io import write
from ase.io.elk import read_elk
from ase.calculators.calculator import (FileIOCalculator, Parameters, kpts2mp,
                                        ReadError, PropertyNotImplementedError,
                                        EigenvalOccupationMixin)


class ELK(FileIOCalculator, EigenvalOccupationMixin):
    command = 'elk > elk.out'
    implemented_properties = ['energy', 'forces']

    def __init__(self, restart=None, ignore_bad_restart_file=False,
                 label=os.curdir, atoms=None, **kwargs):
        """Construct ELK calculator.

        The keyword arguments (kwargs) can be one of the ASE standard
        keywords: 'xc', 'kpts' and 'smearing' or any of ELK'
        native keywords.
        """

        FileIOCalculator.__init__(self, restart, ignore_bad_restart_file,
                                  label, atoms, **kwargs)

    def set_label(self, label):
        self.label = label
        self.directory = label
        self.prefix = ''
        self.out = os.path.join(label, 'INFO.OUT')

    @property
    def out(self):
        return Path(self.directory) / 'INFO.OUT'

    def check_state(self, atoms):
        system_changes = FileIOCalculator.check_state(self, atoms)
        # Ignore boundary conditions (ELK always uses them):
        if 'pbc' in system_changes:
            system_changes.remove('pbc')
        return system_changes

    def set(self, **kwargs):
        changed_parameters = FileIOCalculator.set(self, **kwargs)
        if changed_parameters:
            self.reset()

    def write_input(self, atoms, properties=None, system_changes=None):
        FileIOCalculator.write_input(self, atoms, properties, system_changes)
        self.initialize(atoms)

        directory = Path(self.directory)
        self.parameters.write(directory / 'parameters.ase')
        write(directory / 'elk.in', atoms, parameters=self.parameters,
              format='elk-in')

    def read(self, label):
        FileIOCalculator.read(self, label)
        totenergy = os.path.join(self.directory, 'TOTENERGY.OUT')
        eigval = os.path.join(self.directory, 'EIGVAL.OUT')
        kpoints = os.path.join(self.directory, 'KPOINTS.OUT')

        for filename in [totenergy, eigval, kpoints, self.out]:
            if not os.path.isfile(filename):
                raise ReadError('ELK output file ' + filename + ' is missing.')

        # read state from elk.in because *.OUT do not provide enough digits!
        self.atoms = read_elk(os.path.join(self.directory, 'elk.in'))
        self.parameters = Parameters.read(os.path.join(self.directory,
                                                       'parameters.ase'))
        self.initialize(self.atoms)
        self.read_results()

    def read_results(self):
        converged = self.read_convergence()
        if not converged:
            raise RuntimeError('ELK did not converge! Check ' + self.out)
        self.read_energy()
        if self.parameters.get('tforce'):
            self.read_forces()
        self.width = self.read_electronic_temperature()
        self.nbands = self.read_number_of_bands()
        self.nelect = self.read_number_of_electrons()
        self.niter = self.read_number_of_iterations()
        self.magnetic_moment = self.read_magnetic_moment()

    def initialize(self, atoms):
        if 'spinpol' not in self.parameters:  # honor elk.in settings
            self.spinpol = atoms.get_initial_magnetic_moments().any()
        else:
            self.spinpol = self.parameters['spinpol']

    def get_forces(self, atoms):
        if not self.parameters.get('tforce'):
            raise PropertyNotImplementedError
        return FileIOCalculator.get_forces(self, atoms)

    def read_energy(self):
        fd = open(os.path.join(self.directory, 'TOTENERGY.OUT'), 'r')
        e = float(fd.readlines()[-1]) * Hartree
        self.results['free_energy'] = e
        self.results['energy'] = e

    def read_forces(self):
        lines = open(self.out, 'r').readlines()
        forces = []
        for line in lines:
            if line.rfind('total force') > -1:
                forces.append(np.array([float(f)
                                        for f in line.split(':')[1].split()]))
        self.results['forces'] = np.array(forces) * Hartree / Bohr

    def read_convergence(self):
        converged = False
        text = open(self.out).read().lower()
        if ('convergence targets achieved' in text and
            'reached self-consistent loops maximum' not in text):
            converged = True
        return converged

    # more methods
    def get_electronic_temperature(self):
        return self.width * Hartree

    def get_number_of_bands(self):
        return self.nbands

    def get_number_of_electrons(self):
        return self.nelect

    def get_number_of_iterations(self):
        return self.niter

    def get_number_of_spins(self):
        return 1 + int(self.spinpol)

    def get_magnetic_moment(self, atoms=None):
        return self.magnetic_moment

    def get_magnetic_moments(self, atoms):
        # not implemented yet, so
        # so set the total magnetic moment on the atom no. 0 and fill with 0.0
        magmoms = [0.0 for a in range(len(atoms))]
        magmoms[0] = self.get_magnetic_moment(atoms)
        return np.array(magmoms)

    def get_spin_polarized(self):
        return self.spinpol

    def get_eigenvalues(self, kpt=0, spin=0):
        return self.read_eigenvalues(kpt, spin, 'eigenvalues')

    def get_occupation_numbers(self, kpt=0, spin=0):
        return self.read_eigenvalues(kpt, spin, 'occupations')

    def get_ibz_k_points(self):
        return self.read_kpts(mode='ibz_k_points')

    def get_k_point_weights(self):
        return self.read_kpts(mode='k_point_weights')

    def get_fermi_level(self):
        return self.read_fermi()

    def read_kpts(self, mode='ibz_k_points'):
        """ Returns list of kpts weights or kpts coordinates.  """
        values = []
        assert mode in ['ibz_k_points', 'k_point_weights']
        kpoints = os.path.join(self.directory, 'KPOINTS.OUT')
        lines = open(kpoints).readlines()
        kpts = None
        for line in lines:
            if line.rfind(': nkpt') > -1:
                kpts = int(line.split(':')[0].strip())
                break
        assert kpts is not None
        text = lines[1:]  # remove first line
        values = []
        for line in text:
            if mode == 'ibz_k_points':
                b = [float(c.strip()) for c in line.split()[1:4]]
            else:
                b = float(line.split()[-2])
            values.append(b)
        if len(values) == 0:
            values = None
        return np.array(values)

    def read_number_of_bands(self):
        nbands = None
        eigval = os.path.join(self.directory, 'EIGVAL.OUT')
        lines = open(eigval).readlines()
        for line in lines:
            if line.rfind(': nstsv') > -1:
                nbands = int(line.split(':')[0].strip())
                break
        if self.get_spin_polarized():
            nbands = nbands // 2
        return nbands

    def read_number_of_electrons(self):
        nelec = None
        text = open(self.out).read().lower()
        # Total electronic charge
        for line in iter(text.split('\n')):
            if line.rfind('total electronic charge :') > -1:
                nelec = float(line.split(':')[1].strip())
                break
        return nelec

    def read_number_of_iterations(self):
        niter = None
        lines = open(self.out).readlines()
        for line in lines:
            if line.rfind(' Loop number : ') > -1:
                niter = int(line.split(':')[1].split()[0].strip())  # last iter
        return niter

    def read_magnetic_moment(self):
        magmom = None
        lines = open(self.out).readlines()
        for line in lines:
            if line.rfind('total moment                :') > -1:
                magmom = float(line.split(':')[1].strip())  # last iter
        return magmom

    def read_electronic_temperature(self):
        width = None
        text = open(self.out).read().lower()
        for line in iter(text.split('\n')):
            if line.rfind('smearing width :') > -1:
                width = float(line.split(':')[1].strip())
                break
        return width

    def read_eigenvalues(self, kpt=0, spin=0, mode='eigenvalues'):
        """ Returns list of last eigenvalues, occupations
        for given kpt and spin.  """
        values = []
        assert mode in ['eigenvalues', 'occupations']
        eigval = os.path.join(self.directory, 'EIGVAL.OUT')
        lines = open(eigval).readlines()
        nstsv = None
        for line in lines:
            if line.rfind(': nstsv') > -1:
                nstsv = int(line.split(':')[0].strip())
                break
        assert nstsv is not None
        kpts = None
        for line in lines:
            if line.rfind(': nkpt') > -1:
                kpts = int(line.split(':')[0].strip())
                break
        assert kpts is not None
        text = lines[3:]  # remove first 3 lines
        # find the requested k-point
        beg = 2 + (nstsv + 4) * kpt
        end = beg + nstsv
        if self.get_spin_polarized():
            # elk prints spin-up and spin-down together
            if spin == 0:
                beg = beg
                end = beg + nstsv // 2
            else:
                beg = beg + nstsv // 2
                end = end
        values = []
        for line in text[beg:end]:
            b = [float(c.strip()) for c in line.split()[1:]]
            values.append(b)
        if mode == 'eigenvalues':
            values = [Hartree * v[0] for v in values]
        else:
            values = [v[1] for v in values]
        if len(values) == 0:
            values = None
        return np.array(values)

    def read_fermi(self):
        """Method that reads Fermi energy in Hartree from the output file
        and returns it in eV"""
        E_f = None
        text = open(self.out).read().lower()
        for line in iter(text.split('\n')):
            if line.rfind('fermi                       :') > -1:
                E_f = float(line.split(':')[1].strip())
        E_f = E_f * Hartree
        return E_f
