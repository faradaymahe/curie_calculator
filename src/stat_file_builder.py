from pymatgen.analysis.magnetism.analyzer import MagneticStructureEnumerator
from shutil import copy
from solver import solver
import os
import numpy as np
from tqdm import tqdm
from pymatgen.core import Structure
from pymatgen.io.vasp.sets import MPStaticSet
import matplotlib.pyplot as plt
from pymatgen.io.vasp.outputs import Vasprun
import warnings
from time import sleep, gmtime, strftime

plt.style.use('ggplot')
warnings.filterwarnings('ignore')


def create_job_script(out_path, ntasks=8, job_id=None):
    """
    Args:s
        out_path (str)   -   folder where job script will be created.
        job_id   (str)   -   preferable name of your job in squeue,
        and also the name of the folder for your vasp files.
        As a result in the folder with name 'job_id' will be created job script
    """
    if not job_id:
        job_id = os.path.basename(out_path)

    job_script_text = f"""#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks={ntasks}
#SBATCH --time=02:00:00
#SBATCH --job-name={job_id}
#SBATCH --output=log
#SBATCH --error=err
#SBATCH -p lenovo
module load mpi/impi-5.0.3 intel/mkl-11.2.3 vasp/vasp-5.4.4
mpirun vasp_std"""
    if not os.path.exists(out_path):
        os.mkdir(out_path)
    with open(f'{out_path}/jobscript.sh', 'w') as job:
        job.writelines(job_script_text)


def submit_all_jobs(input_path: str, submit_path: str) -> None:
    submit_full_path = os.path.join(input_path, submit_path)
    initial_path = os.getcwd()
    for folder_name in os.listdir(submit_full_path):
        os.chdir(initial_path)
        tmp_path = os.path.join(submit_full_path, folder_name)
        os.chdir(tmp_path)
        os.system('sbatch jobscript.sh')
    os.chdir(initial_path)


def afm_atom_creator(in_data: list, custom_atom='Po') -> list:
    """
    Args:
        in_data (list) - list of rows from POSCAR type file.

    Add one type of "Fake" atom into the POSCAR structure.
    This allows it to be treated as an atoms with spin up and down respectively,
    thus estimate number of positive and negative contributions into the total energy.
    """
    out_data = in_data.copy()
    out_data[5] = 'Po ' + out_data[5]
    return out_data


def up_down_spin_counter(in_data: list) -> list:
    spin_down = 0
    spin_up = 0
    no_spin = 0
    for row in in_data[8:]:
        if 'spin=-' in row:
            spin_down += 1
        elif 'spin=' in row:
            spin_up += 1
        else:
            no_spin += 1
    return [spin_up, spin_down, no_spin]


def spin_row_replacer(in_data: list) -> list:
    out_data = in_data.copy()
    out_data[6] = ' '.join(str(i)
                           for i in up_down_spin_counter(in_data)) + '\n'
    return out_data


def siman_POSCAR_writer(in_path: str, out_path: str) -> None:
    """
    Args:
        in_path  (str)  -   path to the POSCAR type file which needs to be made readable for siman
        out_path (str)  -   path where refactored version of this file will be written
    """
    with open(in_path) as in_f:
        in_data = in_f.readlines()

    out_data = spin_row_replacer(afm_atom_creator(in_data))

    with open(out_path, 'w+') as out_f:
        out_f.writelines(out_data)


def get_siman_inputs(input_path: str):
    out_path = os.path.join(input_path, 'siman_inputs')
    if not os.path.exists(out_path):
        os.mkdir(out_path)
    vasp_inputs_path = os.path.join(input_path, 'vasp_inputs')
    afm_foldrs = [os.path.join(vasp_inputs_path, i)
                  for i in [i for i in os.listdir(vasp_inputs_path) if 'afm' in i]]
    for folder in tqdm(afm_foldrs):
        tmp_out_path = os.path.join(
            out_path, 'POSCAR_' + folder.split("/")[-1])
        siman_POSCAR_writer(in_path=os.path.join(
            folder, 'POSCAR'), out_path=tmp_out_path)


LDAUJ_dict = {'Co': 0, 'Cr': 0, 'Fe': 0, 'Mn': 0, 'Mo': 0, 'Ni': 0, 'V': 0, 'W': 0,
              'Nb': 0, 'Sc': 0, 'Ru': 0, 'Rh': 0, 'Pd': 0, 'Cu': 0, 'Y': 0, 'Os': 0, 'Ti': 0, 'Zr': 0, 'Re': 0, 'Hf': 0,
              'Pt': 0, 'La': 0}

LDAUU_dict = {'Co': 3.32, 'Cr': 3.7, 'Fe': 5.3, 'Mn': 3.9, 'Mo': 4.38, 'Ni': 6.2, 'V': 3.25, 'W': 6.2,
              'Nb': 1.45, 'Sc': 4.18, 'Ru': 4.29, 'Rh': 4.17, 'Pd': 2.96, 'Cu': 7.71, 'Y': 3.23, 'Os': 2.47, 'Ti': 5.89,
              'Zr': 5.55,
              'Re': 1.28, 'Hf': 4.77, 'Pt': 2.95, 'La': 5.3}

LDAUL_dict = {'Co': 2, 'Cr': 2, 'Fe': 2, 'Mn': 2, 'Mo': 2, 'Ni': 2, 'V': 2, 'W': 2,
              'Nb': 2, 'Sc': 2, 'Ru': 2, 'Rh': 2, 'Pd': 2, 'Cu': 2, 'Y': 2, 'Os': 2, 'Ti': 2, 'Zr': 2, 'Re': 2, 'Hf': 2,
              'Pt': 2, 'La': 2}


def write_static_set(structure, vasp_static_path: str, static_dict: dict) -> None:
    """
    Args:
        structure        (pymatgen.core.structure.Structure)
        vasp_static_path (str)  -  path to the folder for static VASP run
        static_dict      (dict) - dictionary with VASP INCAR keywords

    Write the following files into specified folder:
        INCAR_stat
        jobscript.sh
    """
    if not os.path.exists(vasp_static_path):
        os.mkdir(vasp_static_path)
    static_set = MPStaticSet(structure,
                             user_incar_settings=stat_dict,
                             reciprocal_density=300,
                             force_gamma=True)
    static_set.get_vasp_input().write_input(vasp_static_path)
    create_job_script(vasp_static_path)


def get_VASP_inputs(input_path: str, static_dict: dict) -> None:
    init_structure = Structure.from_file(os.path.join(input_path, 'POSCAR'))
    enum_struct_list = MagneticStructureEnumerator(init_structure,
                                                   transformation_kwargs={'symm_prec': 0.1,
                                                                          'enum_precision_parameter': 0.00001})

    if not os.path.exists(os.path.join(input_path, 'vasp_inputs')):
        os.mkdir(os.path.join(input_path, 'vasp_inputs'))

    for i, magnetic_structure in tqdm(enumerate(enum_struct_list.ordered_structures)):

        magnetic_type = enum_struct_list.ordered_structure_origins[i]

        str_id = magnetic_type + str(i)

        vasp_out_path = os.path.join(input_path, 'vasp_inputs', str_id)

        if not os.path.exists(vasp_out_path):
            os.mkdir(vasp_out_path)

        write_static_set(structure=magnetic_structure,
                         vasp_static_path=vasp_out_path,
                         static_dict=stat_dict)


def check_readiness(input_path: str, submit_path: str) -> None:
    submit_full_path = os.path.join(input_path, submit_path)
    pathes = sorted(os.listdir(submit_full_path))
    converged_list = []
    while len(converged_list) != len(pathes):
        tmp_time = strftime("%H:%M:%S", gmtime())
        print(f'{tmp_time} {submit_path.upper()} optimization')
        converged_list = []
        for folder_name in pathes:
            file_path = os.path.join(submit_full_path, folder_name, 'OSZICAR')
            if os.path.exists(file_path):
                with open(file_path) as f:
                    text = f.readlines()
                    if text and ('E0' in text[-1]):
                        converged_list += [folder_name]
                    else:
                        print(f'{folder_name} not yet converged')
            else:
                print(f'{folder_name} not yet written')
        print('\n')
        sleep(15)
    time = strftime("%H:%M:%S", gmtime())
    print(f'{time} {submit_path.upper()} optimization Finished')


def file_builder(input_path: str, stat_dict: dict):
    assert os.path.exists(
        input_path), f'Input path: {input_path} does not exist!'
    assert os.path.exists(os.path.join(input_path, 'POSCAR')
                          ), f'Please specify POSCAR file in you input folder: {input_path}'

    get_VASP_inputs(input_path=input_path,
                    static_dict=stat_dict)

    get_siman_inputs(input_path)
    copy(os.path.join(input_path, 'POSCAR'), os.path.join(
        input_path, 'siman_inputs', 'POSCAR_fm0'))
    print(strftime("%H:%M:%S", gmtime()), 'All files written. Starting VASP calculations!')
    submit_all_jobs(input_path, submit_path='vasp_inputs')
    sleep(20)
    check_readiness(input_path, submit_path='vasp_inputs')


def get_ecut_files(input_path: str, ecut_range: list) -> None:
    ecut_opt_path = os.path.join(input_path, 'encut')
    if not os.path.exists(ecut_opt_path):
        os.mkdir(ecut_opt_path)
    structure = Structure.from_file(os.path.join(input_path, 'POSCAR'))
    for ecut in ecut_range:
        user_settings = {'ENCUT': ecut, 'EDIFF': 1E-7, 'NCORE': 4,
                         'LDAU': False, 'LVHAR': False, 'LCHARG': False,
                         'LAECHG': False, 'LASPH': False}
        ecut_path = os.path.join(input_path, 'encut', str(ecut))
        if not os.path.exists(ecut_path):
            os.mkdir(ecut_path)
        static_set = MPStaticSet(structure, user_incar_settings=user_settings)
        static_set.get_vasp_input().write_input(ecut_path)
        create_job_script(out_path=ecut_path, ntasks=24)


def en_per_atom_list(input_path: str, mode: str) -> tuple:
    """

    Args:
        input_path (str): path to the folder with POSCAR file
        mode (str): type of calculation it might be 'encut' or 'kpoints'

    Returns:
        energy_arr: structures energies normalized by the number of atom
        params_range: range of optimized parameter (Encut, KPOINTS)
    """
    E_list = []
    calc_fold = os.path.join(input_path, mode)
    params_range = sorted([int(d) for d in os.listdir(calc_fold) if '.' not in d])
    for kpoint_density in tqdm(params_range):
        struct_folder = os.path.join(calc_fold, str(kpoint_density))
        vasprun_path = os.path.join(struct_folder, 'vasprun.xml')
        vasprun = Vasprun(vasprun_path, parse_dos=False, parse_eigen=False)
        E_tot = vasprun.final_energy
        E_list.append(E_tot)
    initial_atoms_num = len(Structure.from_file(os.path.join(input_path, 'POSCAR')))
    energy_arr = np.array(E_list) / initial_atoms_num
    return energy_arr, params_range


def get_ecut(en_per_atom: list, ecut_range) -> int:
    y = np.diff(en_per_atom * 1000)  # diff in meV
    x = ecut_range[1:]
    Ecut = x[np.argmin(abs(y))]
    return Ecut


def plot_encut(input_path: str, en_per_atom, ecut_range: list) -> None:
    x = ecut_range
    y = (en_per_atom - min(en_per_atom)) * 1000  # to meV
    Ecut = get_ecut(en_per_atom, ecut_range)
    i = list(ecut_range).index(Ecut)
    plt.figure(figsize=(12, 6), dpi=200)
    plt.plot(x, y, 'o-', c='r')
    plt.scatter(x[i], y[i], s=200, c='r')
    plt.ylabel('E/atom, meV')
    plt.xlabel('Encut, eV')
    plt.xticks(x, rotation=45, ha='right')
    plt.savefig(os.path.join(input_path, 'Encut.pdf'), bbox_inches='tight')


def write_kpoints(file_name, Rk):
    with open(file_name, 'w') as f:
        st = f"""Automatic mesh
0              ! number of k-points = 0 -> automatic generation scheme 
Auto           ! fully automatic
{Rk}           ! length (R_k)"""
        f.write(st)


def get_kpoints_files(input_path: str, Ecut: int, kpoints_range: list) -> None:
    kpoints_opt_path = os.path.join(input_path, 'kpoints')
    if not os.path.exists(kpoints_opt_path):
        os.mkdir(kpoints_opt_path)

    structure = Structure.from_file(os.path.join(input_path, 'POSCAR'))
    for kpoints in tqdm(kpoints_range):
        user_settings = {'ENCUT': Ecut,
                         'EDIFF': 1E-7, 'NCORE': 4,
                         'LDAU': False,
                         'LVHAR': False,
                         'LCHARG': False,
                         'LAECHG': False,
                         'LASPH': False}
        kpoints_path = os.path.join(input_path, 'kpoints', str(kpoints))
        file_name = os.path.join(kpoints_path, 'KPOINTS')
        if not os.path.exists(kpoints_path):
            os.mkdir(kpoints_path)
        static_set = MPStaticSet(structure, user_incar_settings=user_settings)
        static_set.get_vasp_input().write_input(kpoints_path)
        write_kpoints(file_name, Rk=kpoints)
        create_job_script(out_path=kpoints_path, ntasks=20)


def plot_kpoints(input_path: str, energy_arr, kpoints_range: list) -> None:
    y = (energy_arr - min(energy_arr)) * 1000
    x = kpoints_range
    plt.figure(figsize=(12, 6), dpi=200)
    plt.plot(x, y, 'o-', label='Sigma = 0.05', c='b')
    plt.ylabel('E/atom, meV')
    plt.xlabel(r'$R_K$')
    plt.xticks(x, rotation=45, ha='right')
    plt.legend()
    plt.savefig(os.path.join(input_path, 'Kgrid.pdf'), bbox_inches='tight')


def get_kpoint_density(energy_arr: list, kpoints_range) -> int:
    y = np.diff(energy_arr * 1000)  # diff in meV
    x = kpoints_range[1:]
    R_k = x[np.where(abs(y) < 0.5)[0][0]]
    return R_k


def encut_runner(input_path: str, ecut_range=np.arange(400, 900, 20)):
    print(f'Starting ENCUT optimization:')
    get_ecut_files(input_path, ecut_range)
    submit_all_jobs(input_path=input_path, submit_path='encut')
    check_readiness(input_path, submit_path='encut')
    encut_arr, encut_range = en_per_atom_list(input_path, mode='encut')
    Ecut = get_ecut(encut_arr, encut_range)
    plot_encut(input_path, encut_arr, encut_range)
    print(f'ENCUT optimization finished!')
    print('_' * 60 + '\n')
    return Ecut


def kpoints_runner(input_path: str, kpoints_range=np.arange(20, 100, 10)):
    print(f'Starting KPOINTS optimization:')
    get_kpoints_files(input_path, Ecut, kpoints_range)
    submit_all_jobs(input_path=input_path, submit_path='kpoints')
    print()
    check_readiness(input_path, submit_path='kpoints')
    print(f'KPOINTS optimization finished!')
    energy_arr, kpoints_range = en_per_atom_list(input_path, mode='kpoints')
    plot_kpoints(input_path, energy_arr, kpoints_range)
    R_k = get_kpoint_density(energy_arr, kpoints_range)
    print('_' * 60)
    return R_k


if __name__ == '__main__':
    input_path = os.getcwd()
    magnetic_atom = input('Enter magnetic atom (str): ')
    print(input_path)
    Ecut = encut_runner(input_path)
    print(f'Estimated value of Encut: {Ecut} eV\n')
    R_k = kpoints_runner(input_path)
    print(f'Estimated value of {R_k=}')
    stat_dict = {'ENCUT': Ecut, 'ISMEAR': -5, 'EDIFF': 1E-7, 'SYMPREC': 1E-8, 'NCORE': 4, 'ICHARG': 2,
                 'LDAU': True, 'LDAUJ': LDAUJ_dict, 'LDAUL': LDAUL_dict, 'LDAUU': LDAUU_dict, 'NELM': 120,
                 'LVHAR': False,
                 'LDAUPRINT': 1, 'LDAUTYPE': 2, 'LASPH': True, 'LMAXMIX': 4, 'LWAVE': False, 'LVTOT': False,
                 'LAECHG': False}
    file_builder(input_path, stat_dict=stat_dict)
    solver(input_path, magnetic_atom)
