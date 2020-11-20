#!/usr/bin/env python3

import shutil
import subprocess
import argparse
import datetime
from sys import stdin
import tempfile
import wget
import gzip
import sys
import os
from concurrent.futures import ThreadPoolExecutor

# import util script from parent directory
sys.path.append('..')
import lr_util as util

outdir = 'output'
eval_out_dir = os.path.join(outdir, 'eval')
datadir = 'data'
tdir = os.path.join(datadir, 'training')
aug_config_path = os.path.join('..', '..', '..', 'config')
testseq = os.path.join(datadir, 'chr1.fa.gz')
trset = os.path.join(datadir, tdir, 'train.1784.gb')
refanno = os.path.join(
    datadir, 'ensembl.ensembl_and_ensembl_havana.chr1.CDS.gtf.dupClean.FILTERED.gtf')
hmm_species = 'human_longrunningtest_hmm'
crf_species = 'human_longrunningtest_crf'
jobs = 2


# evaluation on long genomic regions
# try and compare a few parameter sets (HMM, CRF, existing)
# on existing human parameters, try a few prediction options
# [0] -> options
# [1] -> name
# [2] -> description
runs = [
    [['--species=human', '--softmasking=0'], 'human-nosm',
        'standard human parameters, softmasking off'],
    [['--species=human', '--softmasking=1'], 'human-sm',
        'standard human parameters, softmasking'],
    [['--species=human', '--softmasking=1', '--UTR=1', '--alternatives-from-sampling=1', '--sample=100'],
        'human-sm-UTR-alt', 'standard human parameters, softmasking, UTR, alternatives-from-sampling'],
    [['--species=human', '--softmasking=1', '--UTR=1'],
        'human-sm-UTR', 'standard human parameters, softmasking, UTR'],
    [[f'--species={hmm_species}', '--softmasking=1', '--UTR=1'],
        'HMM-sm-UTR', 'HMM-trained parameters, softmasking, UTR'],
    [[f'--species={crf_species}', '--softmasking=1', '--UTR=1'],
        'CRF-sm-UTR', 'CRF-trained parameters, softmasking, UTR']
]

# using 9 regions on chr1, the same regions as used in multi-genome gene prediction (CGP)
chunks = [27, 30, 47, 54, 57, 80, 86, 101, 118]

parser = argparse.ArgumentParser(
    description='Python wrapper to execute single genome test case.')
parser.add_argument('-g', '--pathToGitRepo',
                    help='path to the Augustus Git repository.')
parser.add_argument('-j', '--jobs',
                    help='to set the maximum number of jobs executed in parallel. (default value 2)')
parser.add_argument('-e', '--evalDir', help='path to Eval script.')
args = parser.parse_args()


def clean():
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    if os.path.exists(eval_out_dir):
        shutil.rmtree(eval_out_dir)
    if os.path.exists(datadir):
        shutil.rmtree(datadir)
    if os.path.exists(tdir):
        shutil.rmtree(tdir)

    # remove test species
    hmm_species_path = os.path.join(aug_config_path, 'species', hmm_species)
    if os.path.exists(hmm_species_path):
        shutil.rmtree(hmm_species_path)
    crf_species_path = os.path.join(aug_config_path, 'species', crf_species)
    if os.path.exists(crf_species_path):
        shutil.rmtree(crf_species_path)


def create_test_dirs():
    os.mkdir(outdir)
    os.mkdir(eval_out_dir)
    os.mkdir(datadir)
    os.mkdir(tdir)


def export_environ():
    os.environ['PERL5LIB'] = args.evalDir
    os.environ['AUGUSTUS_CONFIG_PATH'] = aug_config_path


def download(url, target_dir, unzip=False, set_trset=False, set_testseq=False, set_refanno=False):
    url_filename = url.rpartition('/')[2]
    filename = os.path.join(target_dir, url_filename)
    wget.download(url, out=filename)

    if unzip and os.path.isfile(filename):
        new_name = filename.rpartition('.')[0]
        nf = open(new_name, 'wb')
        with gzip.open(filename) as f:
            bindata = f.read()
            nf.write(bindata)
        nf.close()
        if set_trset:
            global trset
            trset = new_name
        if set_testseq:
            global testseq
            testseq = new_name
        if set_refanno:
            global refanno
            refanno = new_name
        os.remove(filename)


def get_test_data():
    print('Downloading required data...')
    download('http://bioinf.uni-greifswald.de/bioinf/downloads/data/aug-test/train.1784.gb.gz',
             tdir, unzip=True, set_trset=True)
    download('http://bioinf.uni-greifswald.de/bioinf/downloads/data/aug-test/chr1.fa.gz',
             datadir, set_testseq=True)
    download('http://bioinf.uni-greifswald.de/bioinf/downloads/data/aug-test/ensembl.ensembl_and_ensembl_havana.chr1.CDS.gtf.dupClean.FILTERED.gtf', datadir)
    print('\n' + 'Download completed.')


def execute(cmd, print_err=True, output=None, error_out=None, mode='w'):
    if output and error_out and mode:
        with open(output, mode) as file:
            with open(error_out, mode) as errfile:
                p = subprocess.Popen(
                    cmd,
                    stdout=file,
                    stderr=errfile,
                    universal_newlines=True)
    elif output and mode:
        with open(output, mode) as file:
            p = subprocess.Popen(
                cmd,
                stdout=file,
                stderr=subprocess.PIPE,
                universal_newlines=True)
    else:
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True)

    p.wait()
    if print_err and p.stderr:
        error = p.stderr.read()
        p.stderr.close()
        if error:
            print(error)


def training():
    training_hmm()
    training_crf()


def training_hmm():
    print('Execute HMM-training...')
    start = datetime.datetime.now()

    cmd = ['../../../scripts/new_species.pl',  f'--species={hmm_species}']
    execute(cmd)

    # train parameters
    cmd = ['../../../bin/etraining',
           f'--species={hmm_species}', trset, '--UTR=on']
    execute(cmd, output=f'{outdir}/etrain_hmm.out',
            error_out=f'{outdir}/etrain_hmm.err', mode='w')

    end = datetime.datetime.now()
    exec_minutes = (end - start).total_seconds() / 60.0
    print(f'Finished HMM-training in {exec_minutes} minutes.')


def training_crf():
    print('Execute CRF-training...')
    start = datetime.datetime.now()

    cmd = ['../../../scripts/new_species.pl',  f'--species={crf_species}']
    execute(cmd)

    # HMM-training to obtain UTR parameters
    cmd = ['../../../bin/etraining',
           f'--species={crf_species}', trset, '--UTR=on']
    execute(cmd, print_err=False)

    # CRF training of CDS parameters (takes about 46m)
    cmd = ['../../../bin/etraining',
           f'--species={crf_species}', trset, '--softmasking=0', '--CRF=on', '--UTR=off']
    execute(cmd, output=f'{outdir}/etrain_crf.out',
            error_out=f'{outdir}/etrain_crf.err', mode='w')

    end = datetime.datetime.now()
    exec_minutes = (end - start).total_seconds() / 60.0
    print(f'Finished CRF-training in {exec_minutes} minutes.')


def compute_chunk_intervall(chunk):
    chunkstep = 2000000
    chunksize = 2499999
    start = chunkstep*(chunk-1)
    end = start+chunksize-1

    return start, end


def execute_run(options, gffname, runname):
    cmds = []
    tmp_filenames = []

    with tempfile.TemporaryDirectory(dir=outdir, prefix='.tmp_') as dir:
        for c in chunks:
            outfile = f'{dir}/augustus_{c}.gff'
            tmp_filenames.append(outfile)
            start, end = compute_chunk_intervall(c)
            cmds.append(['../../../bin/augustus',
                         f'--predictionStart={start}', f'--predictionEnd={end}', testseq, *options, f'--outfile={outfile}'])

        with ThreadPoolExecutor(max_workers=int(jobs)) as executor:
            for cmd in cmds:
                executor.submit(execute, cmd)

        # join output files of analyzed chunks
        input_files = ','.join(tmp_filenames)
        join_cmd = ['../../../auxprogs/joingenes/joingenes',
                    f'--genesets={input_files}', f'--output={gffname}']
        execute(join_cmd)

        # evaluate results
        eval_cmd = [os.path.join(
            args.evalDir, 'evaluate_gtf.pl'), refanno, gffname]
        execute(eval_cmd, output=os.path.join(eval_out_dir, f'{runname}.eval'))


def execute_test():
    for run in runs:
        options = run[0]
        runname = run[1]
        descr = run[2]
        gffname = f'{outdir}/augustus-long-{runname}.gff'

        print(f'Execute Test: {descr}...')
        start = datetime.datetime.now()
        execute_run(options, gffname, runname)
        end = datetime.datetime.now()
        exec_minutes = (end - start).total_seconds() / 60.0
        print(f'Finished Test in {exec_minutes} minutes.')


def analyze_commit():
    info = util.commit_info(args.pathToGitRepo)
    exec_minutes = execute_test()
    util.store_additional_data(
        info[1], info[0], exec_minutes, 'output/test_version_data.json')


if __name__ == '__main__':
    # if args.pathToGitRepo is None:
    #     print('The path to the Augustus Git repository is required, please make use of --pathToGitRepo to pass the path...')
    #     sys.exit()

    if args.evalDir is None:
        print('The path eval script collection, please make use of --evalDir to pass the path...')
        sys.exit()

    if args.jobs:
        jobs = args.jobs

    export_environ()
    clean()
    create_test_dirs()
    get_test_data()
    training()
    execute_test()
