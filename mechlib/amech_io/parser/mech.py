"""
Read the mechanism file
"""

from mechanalyzer.parser import pes
from mechanalyzer.parser.mech import parse_mechanism
from mechanalyzer.builder import sorter


def pes_dictionary(mech_str, mech_type, spc_dct):
    """ Build the PES dct

        Right now just resorts by pes and subpes, may need full suite later.
    """

    # Initialize values used for the basic PES-SUBPES sorting
    sort_str = ['pes', 'subpes', 0]
    isolate_species = ()

    # Build and print the full sorted PES dict
    _, mech_info, _ = parse_mechanism(mech_str, mech_type, spc_dct)
    srt_mch = sorter.sorting(mech_info, spc_dct, sort_str, isolate_species)
    pes_dct = srt_mch.return_pes_dct()

    pes.print_pes_channels(pes_dct)

    # return pes_dct, spc_dct
    return pes_dct