__author__ = 'sudipta'
import sys
import os
import datetime
from operator import itemgetter
import glob
import numpy as np

from pyrate.nci.parallel import Parallel
from pyrate.scripts import run_pyrate
from pyrate import config as cf
from pyrate.scripts import run_prepifg
from pyrate import gamma
from pyrate.shared import Ifg
from pyrate import prepifg
from pyrate import mst

# Constants
MASTER_PROCESS = 0


def main(params=None):
    # Setting up parallelisation
    parallel = Parallel(True)
    MPI_myID = parallel.rank
    num_processors = parallel.size
    ### Master Process ###
    if MPI_myID == MASTER_PROCESS:
        print "Master process found {} worker processors".format(num_processors)

    # Read config file, cropped_and_sampled_tifs are input files to run_pyrate
    if params:
        xlks, ylks, crop = run_pyrate.transform_params(params)
        base_unw_paths = run_pyrate.original_ifg_paths(params[cf.IFG_FILE_LIST])
        cropped_and_sampled_tifs = \
            run_pyrate.get_dest_paths(base_unw_paths, crop, params, xlks)
    else:
        _, cropped_and_sampled_tifs, params = run_pyrate.get_ifg_paths()


    output_dir = params[cf.OUT_DIR]
    mpi_log_filename = os.path.join(output_dir, "mpi_run_pyrate.log")

    ### Master Process ###
    if MPI_myID == MASTER_PROCESS:
        output_log_file = open(mpi_log_filename, "w")
        config_filepath = sys.argv[1]
        configfile = open(config_filepath)
        output_log_file.write("Starting Simulation at: "
                + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        output_log_file.write("Master process found " +
                              str(num_processors) +
                              " worker processors.\n")
        output_log_file.write("\n")
        output_log_file.write("\nConfig Settings: start\n")
        lines = configfile.read()
        for line in lines:
            output_log_file.write(line)
        output_log_file.write("\nConfig Settings: end\n")

        output_log_file.write("\n Input files for run_pyrate are:\n")
        for b in cropped_and_sampled_tifs:
            output_log_file.write(b + "\n")

        output_log_file.close()

    parallel.barrier()

    # Calc mst using MPI
    if MPI_myID == MASTER_PROCESS:
        mst_grid = mpi_mst_calc(MPI_myID, cropped_and_sampled_tifs, mpi_log_filename,
                 num_processors, parallel, params)
        # write mst output to a file
        mst_mat_binary_file = os.path.join(params[cf.OUT_DIR], 'mst_mat')
        np.save(file=mst_mat_binary_file, arr=mst_grid)
    else:
        mpi_mst_calc(MPI_myID, cropped_and_sampled_tifs, mpi_log_filename,
                 num_processors, parallel, params)
    parallel.finalize()



def mpi_mst_calc(MPI_myID, cropped_and_sampled_tifs, mpi_log_filename,
                 num_processors, parallel, params):
    ifgs = run_pyrate.prepare_ifgs_for_networkx_mst(cropped_and_sampled_tifs,
                                                    params)
    top_lefts, bottom_rights, no_tiles = mst.setup_tiles(
        ifgs[0].shape, processes=num_processors)
    # parallel.calc_indices(no_tiles)
    process_indices = parallel.calc_indices(no_tiles)
    process_top_lefts = [itemgetter(p)(top_lefts)
                         for p in process_indices]
    process_bottom_rights = [itemgetter(p)(bottom_rights)
                             for p in process_indices]
    print 'Processor {mpi_id} has {processes} ' \
          'tiles out of {num_files}'.format(mpi_id=MPI_myID,
                                            processes=len(process_indices),
                                            num_files=no_tiles)
    result_process = mst.mst_multiprocessing_map(
        process_top_lefts, process_bottom_rights,
        cropped_and_sampled_tifs, ifgs[0].shape, no_ifgs=len(ifgs)
    )
    parallel.barrier()
    # send the result arrays
    if MPI_myID != MASTER_PROCESS:
        parallel.send(result_process, destination=MASTER_PROCESS, tag=MPI_myID)
        print "sent result from process", MPI_myID

    if MPI_myID == MASTER_PROCESS:
        result = result_process
        # combine the mst from the other processes
        for i in range(1, num_processors):
            result_remote_processes = \
                parallel.receive(source=i, tag=-1, return_status=False)
            result += result_remote_processes

        output_log_file = open(mpi_log_filename, "a")
        output_log_file.write("\n\n Mst caclulation finished\n")
        output_log_file.close()
        return result


def clean_up_old_files():
    files = glob.glob(os.path.join('out', '*.tif'))
    for f in files:
        os.remove(f)
        print 'removed', f


if __name__ == '__main__':
    main()
