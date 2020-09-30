import numpy as np
import pytest
from ase.build import bulk
from ase.calculators.lj import LennardJones
from ase.calculators.emt import EMT
from ase.calculators.qmmm import ForceQMMM, RescaledCalculator
from ase.eos import EquationOfState
from ase.optimize import FIRE
from ase.neighborlist import neighbor_list
from ase.geometry import get_distances


@pytest.mark.slow
def test_forceqmmm():

    # parameters
    N_cell = 2
    R_QMs = np.array([3, 7])

    # setup bulk and MM region
    bulk_at = bulk("Cu", cubic=True)
    sigma = (bulk_at * 2).get_distance(0, 1) * (2. ** (-1. / 6))
    mm = LennardJones(sigma=sigma, epsilon=0.05)
    qm = EMT()

    # test number of atoms in qm_buffer_mask for
    # spherical region in a fully periodic cell
    bulk_at = bulk("Cu", cubic=True)
    alat = bulk_at.cell[0, 0]
    N_cell_geom = 10
    at0 = bulk_at * N_cell_geom
    r = at0.get_distances(0, np.arange(len(at0)), mic=True)
    print("N_cell", N_cell_geom, 'N_MM', len(at0), "Size", N_cell_geom * alat)
    qm_rc = 5.37  # cutoff for EMC()

    for R_QM in [1.0e-3,  # one atom in the center
                 alat / np.sqrt(2.0) + 1.0e-3,  # should give 12 nearest
                                                # neighbours + central atom
                 alat + 1.0e-3]:  # should give 18 neighbours + central atom

        at = at0.copy()
        qm_mask = r < R_QM
        qm_buffer_mask_ref = r < 2 * qm_rc + R_QM
        # exclude atoms that are too far (in case of non spherical region)
        # this is the old way to do it
        _, r_qm_buffer = get_distances(at.positions[qm_buffer_mask_ref],
                                       at.positions[qm_mask], at.cell, at.pbc)
        updated_qm_buffer_mask = np.ones_like(at[qm_buffer_mask_ref])
        for i, r_qm in enumerate(r_qm_buffer):
            if r_qm.min() > 2 * qm_rc:
                updated_qm_buffer_mask[i] = False

        qm_buffer_mask_ref[qm_buffer_mask_ref] = updated_qm_buffer_mask

        print(f'R_QM             {R_QM}   N_QM        {qm_mask.sum()}')
        print(f'R_QM + buffer: {2 * qm_rc + R_QM:.2f}'
              f' N_QM_buffer {qm_buffer_mask_ref.sum()}')
        print(f'                     N_total:    {len(at)}')
        qmmm = ForceQMMM(at, qm_mask, qm, mm, buffer_width=2 * qm_rc)
        # build qm_buffer_mask and test it
        qmmm.initialize_qm_buffer_mask(at)
        print(f'      Calculator N_QM_buffer:'
              f'    {qmmm.qm_buffer_mask.sum().sum()}')
        assert qmmm.qm_buffer_mask.sum() == qm_buffer_mask_ref.sum()
        # same test for qmmm.get_cluster()
        qm_cluster = qmmm.get_qm_cluster(at)
        assert len(qm_cluster) == qm_buffer_mask_ref.sum()

    # test qm cell shape and choice of pbc:
    # make a non-periodic pdc in a direction
    # if qm_radius + buffer is larger than the original cell
    # keep the periodic cell otherwise i. e. if cell[i, i] > qm_radius + buffer
    # test the case of a cluster in a fully periodic cell:
    # fist qm_radius + buffer > cell,
    # thus should give a cluster with pbc=[T, T, T]
    # (qm cluster is the same as the original cell)
    at0 = bulk_at * 4
    size = at0.cell[0, 0]
    r = at0.get_distances(0, np.arange(len(at0)), mic=True)
    # should give 12 nearest neighbours + atom in the center
    R_QM = alat / np.sqrt(2.0) + 1.0e-3
    qm_mask = r < R_QM
    """
    print(f"R_QM: {R_QM:.4f}")
    print(f"R_QM + buffer: {1.2 * size + R_QM:.2f}")
    print(f"Cell size: {np.diagonal(at0.cell)}")
    """
    qmmm = ForceQMMM(at0, qm_mask, qm, mm, buffer_width=1.2 * size)
    # build qm_buffer_mask to build the cell
    qmmm.initialize_qm_buffer_mask(at0)
    qm_cluster = qmmm.get_qm_cluster(at0)
    # should give pbc = [T, T, T]
    for qm_cluster_pbc in qmmm.qm_cluster_pbc:
        assert qm_cluster_pbc
    # same test for qmmm.get_cluster()
    for qm_cluster_pbc in qm_cluster.pbc:
        assert qm_cluster_pbc

    # should have the same cell as the original atoms
    for qm_cell_dir, orinial_cell_dir in zip(np.diag(qmmm.qm_cluster_cell),
                                             np.diag(at0.cell)):
        assert qm_cell_dir == orinial_cell_dir
    # same test for qmmm.get_cluster()
    for qm_cluster_cell_dir, orinial_cell_dir in zip(np.diag(qm_cluster.cell),
                                                     np.diag(at0.cell)):
        assert qm_cluster_cell_dir == orinial_cell_dir

    # test the case of a fully spherical cell with in a fully periodic cell
    qmmm = ForceQMMM(at0, qm_mask, qm, mm, buffer_width=0.25 * size)
    # equal to 1 alat
    """ 
    print(f"R_QM: {R_QM:.4f}")
    print(f"R_QM + buffer: {0.25 * size + R_QM:.2f}")
    print(f"Cell size: {np.diagonal(at0.cell)}")
    """
    # build qm_buffer_mask to build the cell
    qmmm.initialize_qm_buffer_mask(at0)
    # should give pbc = [F, F, F]
    qm_cluster = qmmm.get_qm_cluster(at0)
    for qm_cluster_pbc in qmmm.qm_cluster_pbc:
        assert not qm_cluster_pbc
    # same test for qmmm.get_cluster()
    for qm_cluster_pbc in qm_cluster.pbc:
        assert not qm_cluster_pbc

    # should NOT have the same cell as the original atoms
    for qm_cell_dir, original_cell_dir in zip(np.diag(qmmm.qm_cluster_cell),
                                              np.diag(at0.cell)):
        assert not qm_cell_dir == original_cell_dir
    # same test for qmmm.get_cluster()
    for qm_cluster_cell_dir, orinial_cell_dir in zip(np.diag(qm_cluster.cell),
                                                     np.diag(at0.cell)):
        assert not qm_cluster_cell_dir == orinial_cell_dir
    # test mixed scenario
    at0 = bulk_at * [4, 4, 1]
    r = at0.get_distances(0, np.arange(len(at0)), mic=True)
    qm_mask = r < R_QM

    qmmm = ForceQMMM(at0, qm_mask, qm, mm, buffer_width=0.25 * size)
    # equal to 1 alat
    # build qm_buffer_mask to build the cell
    qmmm.initialize_qm_buffer_mask(at0)
    qm_cluster = qmmm.get_qm_cluster(at0)
    # should give pbc = [F, F, T]
    for qm_cluster_pbc in qmmm.qm_cluster_pbc[:2]:
        assert not qm_cluster_pbc
    assert qmmm.qm_cluster_pbc[2]  # Z should be periodic
    # same test for qmmm.get_cluster()
    for qm_cluster_pbc in qm_cluster.pbc[:2]:
        assert not qm_cluster_pbc
    assert qm_cluster.pbc[2]  # Z should be periodic

    # should NOT have the same cell as the original atoms in X and Y directions
    for qm_cell_dir, original_cell_dir in \
            zip(np.diag(qmmm.qm_cluster_cell)[:2], np.diag(at0.cell)[:2]):
        assert not qm_cell_dir == original_cell_dir
    # should be the same in Z direction
    assert np.diag(qmmm.qm_cluster_cell)[2] == np.diag(at0.cell)[2]
    # same test for qmmm.get_cluster()
    for qm_cluster_cell_dir, original_cell_dir in \
            zip(np.diag(qm_cluster.cell)[:2], np.diag(at0.cell)[:2]):
        assert not qm_cluster_cell_dir == original_cell_dir
    # should be the same in Z direction
    assert np.diag(qm_cluster.cell)[2] == np.diag(at0.cell)[2]

    # compute MM and QM equations of state
    def strain(at, e, calc):
        at = at.copy()
        at.set_cell((1.0 + e) * at.cell, scale_atoms=True)
        at.calc = calc
        v = at.get_volume()
        e = at.get_potential_energy()
        return v, e

    eps = np.linspace(-0.01, 0.01, 13)
    v_qm, E_qm = zip(*[strain(bulk_at, e, qm) for e in eps])
    v_mm, E_mm = zip(*[strain(bulk_at, e, mm) for e in eps])

    eos_qm = EquationOfState(v_qm, E_qm)
    v0_qm, E0_qm, B_qm = eos_qm.fit()
    a0_qm = v0_qm ** (1.0 / 3.0)

    eos_mm = EquationOfState(v_mm, E_mm)
    v0_mm, E0_mm, B_mm = eos_mm.fit()
    a0_mm = v0_mm ** (1.0 / 3.0)

    mm_r = RescaledCalculator(mm, a0_qm, B_qm, a0_mm, B_mm)
    v_mm_r, E_mm_r = zip(*[strain(bulk_at, e, mm_r) for e in eps])

    eos_mm_r = EquationOfState(v_mm_r, E_mm_r)
    v0_mm_r, E0_mm_r, B_mm_r = eos_mm_r.fit()
    a0_mm_r = v0_mm_r ** (1.0 / 3)

    # check match of a0 and B after rescaling is adequate
    # 0.1% error in lattice constant
    assert abs((a0_mm_r - a0_qm) / a0_qm) < 1e-3
    assert abs((B_mm_r - B_qm) / B_qm) < 0.05  # 5% error in bulk modulus

    # plt.plot(v_mm, E_mm - np.min(E_mm), 'o-', label='MM')
    # plt.plot(v_qm, E_qm - np.min(E_qm), 'o-', label='QM')
    # plt.plot(v_mm_r, E_mm_r - np.min(E_mm_r), 'o-', label='MM rescaled')
    # plt.legend()

    at0 = bulk_at * N_cell
    r = at0.get_distances(0, np.arange(1, len(at0)), mic=True)
    print(len(r))
    del at0[0]  # introduce a vacancy
    print("N_cell", N_cell, 'N_MM', len(at0),
          "Size", N_cell * bulk_at.cell[0, 0])

    ref_at = at0.copy()
    ref_at.calc = qm
    opt = FIRE(ref_at)
    opt.run(fmax=1e-3)
    u_ref = ref_at.positions - at0.positions

    us = []
    for R_QM in R_QMs:
        at = at0.copy()
        qm_mask = r < R_QM
        qm_buffer_mask_ref = r < 2 * qm.rc + R_QM
        print(f'R_QM             {R_QM}   N_QM        {qm_mask.sum()}')
        print(f'R_QM + buffer: {2 * qm.rc + R_QM:.2f}'
              f' N_QM_buffer {qm_buffer_mask_ref.sum()}')
        print(f'                     N_total:    {len(at)}')
        # Warning: Small size of the cell and large size of the buffer
        # lead to the qm calculation performed on the whole cell.
        qmmm = ForceQMMM(at, qm_mask, qm, mm, buffer_width=2 * qm.rc)
        qmmm.initialize_qm_buffer_mask(at)
        at.calc = qmmm
        opt = FIRE(at)
        opt.run(fmax=1e-3)
        us.append(at.positions - at0.positions)

    # compute error in energy norm |\nabla u - \nabla u_ref|
    def strain_error(at0, u_ref, u, cutoff, mask):
        I, J = neighbor_list('ij', at0, cutoff)
        I, J = np.array([(i, j) for i, j in zip(I, J) if mask[i]]).T
        v = u_ref - u
        dv = np.linalg.norm(v[I, :] - v[J, :], axis=1)
        return np.linalg.norm(dv)

    du_global = [strain_error(at0, u_ref, u, 1.5 * sigma,
                              np.ones(len(r))) for u in us]
    du_local = [strain_error(at0, u_ref, u, 1.5 * sigma, r < 3.0) for u in us]

    print('du_local', du_local)
    print('du_global', du_global)

    # check local errors are monotonically decreasing
    assert np.all(np.diff(du_local) < 0)

    # check global errors are monotonically converging
    assert np.all(np.diff(du_global) < 0)

    # biggest QM/MM should match QM result
    assert du_local[-1] < 1e-10
    assert du_global[-1] < 1e-10
