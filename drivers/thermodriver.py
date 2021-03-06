""" Driver for thermochemistry evaluations including
    heats-of-formation and NASA polynomials describing
    thermodynamic quantities: Enthalpy, Entropy, Gibbs
"""

import os
from routines.pf import thermo as thmroutines
from routines.pf import runner as pfrunner
from routines.pf.models import ene
from lib.amech_io import writer
from lib.amech_io import parser
from lib.amech_io.parser.model import pf_level_info, pf_model_info
# from lib.structure import instab
from lib import filesys
from automol.inchi import formula_string as fstring

def run(spc_dct,
        pes_model_dct, spc_model_dct,
        thy_dct,
        rxn_lst,
        run_inp_dct,
        write_messpf=True,
        run_messpf=True,
        run_nasa=True):
    """ main driver for thermo run
    """

    # Pull stuff from dcts for now
    save_prefix = run_inp_dct['save_prefix']
    run_prefix = run_inp_dct['run_prefix']

    # Build a list of the species to calculate thermochem for loops below
    # Set reaction list with unstable species broken apart
    # print('Checking stability of all species...')
    # rxn_lst = instab.break_all_unstable2(
        # rxn_lst, spc_dct, spc_model_dct, thy_dct, save_prefix)
    spc_queue = parser.species.build_queue(rxn_lst)
    spc_queue = parser.species.split_queue(spc_queue)
    # Build the paths [(messpf, nasa)], models and levels for each spc
    starting_path = os.getcwd()
    ckin_path = os.path.join(starting_path, 'ckin')
    thm_paths = []
    for spc_name, (_, mods, _, _) in spc_queue:
        thm_path = {}
        for idx, mod in enumerate(mods):
            thm_path[mod] = pfrunner.thermo_paths(spc_dct[spc_name], run_prefix, idx)
        thm_paths.append(thm_path)
    pf_levels = {}
    pf_models = {}
    for _, (_, mods, _, _) in spc_queue:
        for mod in mods:
            pf_levels[mod] = pf_level_info(spc_model_dct[mod]['es'], thy_dct)
            pf_models[mod] = pf_model_info(spc_model_dct[mod]['pf'])
            pf_models[mod]['ref_scheme'] = (
                spc_model_dct[mod]['options']['ref_scheme']
                if 'ref_scheme' in spc_model_dct[mod]['options'] else 'none')
            pf_models[mod]['ref_enes'] = (
                spc_model_dct[mod]['options']['ref_enes']
                if 'ref_enes' in spc_model_dct[mod]['options'] else 'none')
    # Write and Run MESSPF inputs to generate the partition functions
    if write_messpf:

        print(('\n\n------------------------------------------------' +
               '--------------------------------------'))
        print('\nPreparing MESSPF input files for all species')
        pf_paths = {}
        for idx, (spc_name, (pes_model, spc_models, _, _)) in enumerate(spc_queue):
            pf_paths[idx] = {}
            for spc_model in spc_models:
                print('spc_model', spc_model)
                global_pf_str = thmroutines.qt.make_pf_header(
                    pes_model_dct[pes_model]['therm_temps'])
                spc_str, dat_str_dct = thmroutines.qt.make_spc_mess_str(
                    spc_dct, spc_name,
                    pf_models[spc_model], pf_levels[spc_model],
                    run_prefix, save_prefix)
                messpf_inp_str = thmroutines.qt.make_messpf_str(
                    global_pf_str, spc_str)
                print('\n\n')
                print('MESSPF Input String:\n')
                print('\n\n')
                pfrunner.mess.write_mess_file(
                    messpf_inp_str, dat_str_dct, thm_paths[idx][spc_model][0],
                    filename='pf.inp')

                # Write MESS file into job directory
                cpy_path = pfrunner.write_cwd_pf_file(
                    messpf_inp_str, spc_dct[spc_name]['inchi'])
                pf_paths[idx][spc_model] = cpy_path

    # Run the MESSPF files that have been written
    if run_messpf:

        print(('\n\n------------------------------------------------' +
               '--------------------------------------'))
        print('\nRunning MESSPF calculations for all species')

        for idx, (spc_name, (pes_model, spc_models, coeffs, operators)) in enumerate(spc_queue):
            print('\n{}'.format(spc_name))
            for midx, spc_model in enumerate(spc_models):
                pfrunner.run_pf(thm_paths[idx][spc_model][0])
                temps, logq, dq_dt, d2q_dt2 = pfrunner.mess.read_messpf(
                    thm_paths[idx][spc_model][0])
                if midx == 0:
                    coeff = coeffs[midx]
                    final_pf = [temps, logq, dq_dt, d2q_dt2]
                else:
                    pf2 = temps, logq, dq_dt, d2q_dt2
                    coeff = coeffs[midx]
                    operator = operators[midx-1]
                    if coeff < 0:
                        coeff = abs(coeff)
                        if operator == 'multiply':
                            operator = 'divide'
                    if operator == 'divide':
                        pfrunner.mess.divide_pfs(final_pf, pf2, coeff)
                    elif operator == 'multiply':
                        pfrunner.mess.multiply_pfs(final_pf, pf2, coeff)
            thm_paths[idx]['final'] = pfrunner.thermo_paths(
                spc_dct[spc_name], run_prefix, len(spc_models))
            pfrunner.mess.write_mess_output(
                fstring(spc_dct[spc_name]['inchi']),
                final_pf, thm_paths[idx]['final'][0],
                filename='pf.dat')

    # Use MESS partition functions to compute thermo quantities
    if run_nasa:

        print(('\n\n------------------------------------------------' +
               '--------------------------------------'))
        print('\nRunning Thermochemistry calculations for all species')

        chn_basis_ene_dct = {}

        for idx, (spc_name, (pes_model, spc_models, _, _)) in enumerate(spc_queue):
            print('\n{}'.format(spc_name))
            spc_model = spc_models[0]
            if not spc_model in chn_basis_ene_dct:
                chn_basis_ene_dct[spc_model] = {}
            # Get the reference scheme and energies
            ref_scheme = spc_model_dct[spc_model]['options']['ref_scheme']
            ref_enes = spc_model_dct[spc_model]['options']['ref_enes']

            # Determine info about the basis species used in thermochem calcs
            basis_dct, uniref_dct = thmroutines.basis.prepare_refs(
                ref_scheme, spc_dct, [[spc_name, None]])

            # Get the basis info for the spc of interest
            spc_basis, coeff_basis = basis_dct[spc_name]

            # Get the energies for the spc and its basis
            ene_basis = []
            energy_missing = False
            for spc_basis_i in spc_basis:
                if spc_basis_i in chn_basis_ene_dct[spc_model]:
                    print('Energy already found for basis species: ', spc_basis_i)
                    ene_basis.append(chn_basis_ene_dct[spc_model][spc_basis_i])
                else:
                    print('Energy will be determined for basis species: ', spc_basis_i)
                    energy_missing = True
            if not energy_missing:
                pf_filesystems = filesys.models.pf_filesys(
                    spc_dct[spc_name], pf_levels[spc_model],
                    run_prefix, save_prefix, saddle=False)
                ene_spc = ene.read_energy(
                    spc_dct[spc_name], pf_filesystems, pf_models[spc_model],
                    pf_levels[spc_model],
                    run_prefix, read_ene=True, read_zpe=True, saddle=False)
            else:
                ene_spc, ene_basis = thmroutines.basis.basis_energy(
                    spc_name, spc_basis, uniref_dct, spc_dct,
                    pf_levels[spc_model], pf_models[spc_model],
                    run_prefix, save_prefix)
                for spc_basis_i, ene_basis_i in zip(spc_basis, ene_basis):
                    chn_basis_ene_dct[spc_model][spc_basis_i] = ene_basis_i

            # Calculate and store the 0 K Enthalpy
            hf0k = thmroutines.heatform.calc_hform_0k(
                ene_spc, ene_basis, spc_basis, coeff_basis, ref_set=ref_enes)
            spc_dct[spc_name]['Hfs'] = [hf0k]

        # Write the NASA polynomials in CHEMKIN format
        ckin_nasa_str = ''
        ckin_path = os.path.join(starting_path, 'ckin')
        for idx, (spc_name, (pes_model, spc_models, _, _)) in enumerate(spc_queue):

            print("\n\nStarting NASA polynomials calculation for ", spc_name)

            # Read the temperatures from the pf.dat file, check if viable
            temps = pfrunner.read_messpf_temps(thm_paths[idx]['final'][0])
            thmroutines.nasapoly.print_nasa_temps(temps)

            # Write the NASA polynomial in CHEMKIN-format string
            ref_scheme = spc_model_dct[spc_model]['options']['ref_scheme']
            for spc_model in spc_models:
                ckin_nasa_str += writer.ckin.model_header(
                    pf_levels[spc_model], pf_models[spc_model], refscheme=ref_scheme)

            # Build POLY
            ckin_nasa_str += thmroutines.nasapoly.build_polynomial(
                spc_name, spc_dct, temps,
                thm_paths[idx]['final'][0], thm_paths[idx]['final'][1], starting_path)
            ckin_nasa_str += '\n\n'

        # Write all of the NASA polynomial strings
        writer.ckin.write_nasa_file(ckin_nasa_str, ckin_path)
