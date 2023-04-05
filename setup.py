#!/usr/bin/python

import os
import re
import sys
import stat
import shlex
import getpass
import argparse
import subprocess

from os.path import join
from os.path import isdir
from os.path import isfile
from os.path import abspath
from os.path import dirname
from os.path import expandvars

from colorama import Fore
from colorama import Style

from multiprocessing import cpu_count


def command_exited_nonzero(cmd):
    try:
        with open(os.devnull, 'w') as devnull:
            subprocess.check_output(cmd,
                                    shell=True,
                                    stderr=devnull)
        return False
    except subprocess.CalledProcessError:
        return True


def is_package_installed(pkg):
    if pkg == "docker.io":
        return os.path.isfile("/usr/bin/docker")
    if (os.path.isfile(os.path.join("/usr/bin", pkg)) or
            os.path.isfile(os.path.join("/bin", pkg))):
        return True
    if command_exited_nonzero("dpkg -s {}".format(pkg)):
        # maybe it is a python package
        try:
            python_pkg = pkg.split("python-")[1]
            return not command_exited_nonzero("python -c \"import {}\""
                                              .format(python_pkg))
        # pkg is not a string of "python-{}"
        except IndexError:
            return False
    else:
        return True


# if not is_package_installed("python-colorama"):
#     subprocess.check_call(['sudo', 'apt-get',
#                            'install', '-y', 'python-colorama'])

# this is set to denote user is already in docker group
ALREADY_IN_DOCKER_GROUP = False
LLVM_VERSION = "3.6.2"
DOCKER_NAME = "lava32"

LAVA_DIR = dirname(abspath(sys.argv[0]))
os.chdir(LAVA_DIR)

BUILD_DIR = join(os.environ["HOME"], "build")
try:
    os.mkdir(BUILD_DIR)
except Exception:
    pass

# try to import lava.mak as a config file
# if not then resort to default locations for llvm and panda
try:
    def_lines = (line.strip() for line in open("lava.mak", "r")
                 if not line.strip().startswith("#")
                 and line.strip() != "")
    def_lines = (line.split(":=") for line in def_lines)
    def_lines = ((line[0].strip(), line[1].strip()) for line in def_lines)
    LAVA_CONFS = dict(def_lines)
    #PANDA_DIR = LAVA_CONFS["PANDA_SRC_PATH"]
    #PANDA_DIR = expandvars(PANDA_DIR)
    LLVM_DIR = LAVA_CONFS["LLVM_SRC_PATH"]
    LLVM_DIR = expandvars(LLVM_DIR)
except Exception:
    LLVM_DIR = join(BUILD_DIR, "llvm-" + LLVM_VERSION)

# Panda must the submodule
PANDA_DIR = abspath(join(LAVA_DIR, "panda/src"))
PANDA_BUILD_DIR = join(PANDA_DIR, '../build')

# panda/scripts/install_ubuntu.sh
PANDA_UBUNTU = "https://raw.githubusercontent.com/panda-re/panda" \
                "/master/panda/scripts/install_ubuntu.sh"

# libc6 needed for compiling btrace
# libjsoncpp needed for fbi json parsing
LAVA_DEPS = ["libjsoncpp-dev", "postgresql", "jq", "psycopg2",
             "SQLAlchemy", "socat", "libpq-dev", "cmake",
             "docker.io", "bc", "psutil",
             "lockfile", "genisoimage", "inotify-tools",
             "build-essential", "python3-pip", "libprotobuf-c0-dev",
             "libodb-pgsql-2.4", "libfdt-dev"]

PANDA_MAK = """
# This is an autogenerated file from lava/setup.py.
PANDA_SRC_PATH := {PANDA_DIR}
PANDA_BUILD_DIR := {PANDA_DIR}/../build
"""
LLVM_MAK = """
# This is an autogenerated file from lava/setup.py.
LLVM_SRC_PATH := {LLVM_SRC_PATH}
LLVM_BUILD_PATH := {LLVM_BUILD_PATH}
LLVM_BIN_PATH := $(LLVM_BUILD_PATH)/install/bin
"""


def progress(msg):
    print('')
# PANDA_UBUNTU = "https://goo.gl/GNMNmJ"
    print(Fore.GREEN + '[setup.py] ' + Fore.RESET + Style.BRIGHT
          + msg + Style.RESET_ALL)


def error(msg):
    print('')
    print(Fore.RED + '[setup.py] ' + Fore.RESET + Style.BRIGHT
          + msg + Style.RESET_ALL)
    sys.exit(1)


def cmd_to_list(cmd):
    cmd_args = shlex.split(cmd) if isinstance(cmd, str) else cmd
    cmd = subprocess.list2cmdline(cmd_args)
    return cmd, cmd_args


def run(cmd):
    cmd, cmd_args = cmd_to_list(cmd)
    try:
        progress("Running [{}] . . . ".format(cmd))
        subprocess.check_call(cmd_args)
    except subprocess.CalledProcessError:
        error("[{}] cmd did not execute properly.".format(cmd))
        raise


def user_in_docker(username):
    # grep exits with 0 if pattern found, 1 otherwise
    return not command_exited_nonzero("groups {} | grep docker"
                                      .format(username))


DOCKER_MAP_DIRS = [LAVA_DIR, os.environ['HOME']]
DOCKER_MAP_FILES = ['/etc/passwd', '/etc/group',
                    '/etc/shadow', '/etc/gshadow']
map_dirs_dedup = []
# quadratic but who cares
for d in DOCKER_MAP_DIRS:
    add = True
    for d2 in DOCKER_MAP_DIRS:
        if d is not d2 and d.startswith(d2):
            add = False
            break
    if add:
        map_dirs_dedup.append(d)

map_dirs_args = sum([['-v', '{0}:{0}'.format(d)]
                     for d in map_dirs_dedup], [])
map_files_args = sum([['-v', '{0}:{0}:ro'.format(d)]
                      for d in DOCKER_MAP_FILES], [])

ENV_VARS = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy',
            'https_proxy', 'no_proxy']
env_map = {k: os.environ[k] for k in ENV_VARS if k in os.environ}
env_var_args = sum([['-e', '{}={}'.format(k, v)]
                    for k, v in env_map.items()], [])
build_args = sum([['--build-arg', '{}={}'.format(k, v)]
                  for k, v in env_map.items()], [])

ALREADY_IN_DOCKER_GROUP = user_in_docker(getpass.getuser())


def run_docker(cmd):
    cmd, cmd_args = cmd_to_list(cmd)
    sudo_args = [] if ALREADY_IN_DOCKER_GROUP else ['sudo']
    # Have to be sudo in case we just installed docker
    # and don't have the group yet.
    cmd_args = sudo_args + ['docker', 'run', '--rm'] + map_dirs_args + \
        map_files_args + env_var_args + \
        [DOCKER_NAME, 'su', '-l', getpass.getuser(), '-c', cmd]
    try:
        progress("Running in docker [{}] . . . ".format(cmd))
        # print "[{}]".format(" ".join(cmd_args))
        cmd_str = "[{}]".format(" ".join(cmd_args))
        print(f"{cmd_str}")
        subprocess.check_call(cmd_args)
    except subprocess.CalledProcessError:
        error("[{}] cmd did not execute properly.")
        raise


def main():
    parser = argparse.ArgumentParser(description='Setup LAVA')
    parser.add_argument('-s', '--skip_docker_build', action='store_true',
                        default=False,
                        help='Whether or not to skip building docker image')
    parser.add_argument('-f', '--fast', action='store_true', default=False,
                        help='Whether or not to skip building \
                        binutils and glibc')
    args = parser.parse_args()
    IGNORE_DOCKER = args.skip_docker_build

    progress("In LAVA dir at {}".format(LAVA_DIR))
    # check to make sure we are not running as root/sudo
    if os.getuid() == 0:
        error("sudo/root privileges detected. \
              Run as user!\nUSAGE: {}".format(sys.argv[0]))

    progress("Installing LAVA apt-get dependencies")
    # if not all(map(is_package_installed, LAVA_DEPS)):
    #     run(['sudo', 'apt-get', '-y', 'install'] + LAVA_DEPS)

    # set up postgres authentication.
    if not isfile(join(os.environ['HOME'], '.pgpass')):
        postgres_depends = subprocess.check_output(['dpkg-query', '-W', '-f',
                                                    '${depends}',
                                                    'postgresql']).splitlines()
        postgres_pkg = [d for d in postgres_depends
                        if re.match(r'postgresql-[0-9]+.?[0-9]+', d.decode('utf-8'))][0]
        postgres_version = postgres_pkg.decode('utf-8').replace('postgresql-', '')
        pg_hba = "/etc/postgresql/{}/main/pg_hba.conf".format(postgres_version)
        postgres_password = 'postgrespostgres'
        run(['sudo', 'sed', '-i.bak', '-E',
             r's/^(local\s+all\s+postgres\s+)md5$/\1peer/', pg_hba])
        run("sudo service postgresql reload")
        password_sql = "ALTER USER postgres WITH PASSWORD '{}';" \
            .format(postgres_password)
        run(['sudo', '-u', 'postgres', 'psql', '-c', password_sql])
        pgpass = join(os.environ['HOME'], '.pgpass')
        with open(pgpass, 'w') as f:
            f.write('*:*:*:postgres:{}'.format(postgres_password))
        os.chmod(pgpass, stat.S_IRUSR | stat.S_IWUSR)
        run(['sudo', 'sed', '-i.bak', '-E',
             r's/^(local\s+all\s+postgres\s+)peer$/\1md5/', pg_hba])
        run("sudo service postgresql reload")

    # check that user has docker install and docker privileges
    progress("Checking if user is in docker group")
    if not ALREADY_IN_DOCKER_GROUP:
        run(['sudo', 'usermod', '-a', '-G', 'docker', getpass.getuser()])

    # check that user has the LAVA build docker vm build
    # if not run python scripts/build-docker.py
    if not IGNORE_DOCKER:
        progress("Checking that {} docker is properly built"
                 .format(DOCKER_NAME))
        sudo_args = [] if ALREADY_IN_DOCKER_GROUP else ['sudo']
        run(sudo_args + ['docker', 'build', '-t',
                         DOCKER_NAME, join(LAVA_DIR, 'docker')] + build_args)
        compile_cmd = ['cd', join(LAVA_DIR, 'tools', 'btrace'),
                       '&&', 'bash', 'compile.sh']
        run_docker(['bash', '-c', subprocess.list2cmdline(compile_cmd)])

    progress("Initializing PANDA submodule")
    run(['git', 'submodule', 'init'])
    run(['git', 'submodule', 'update'])

    # check for location of panda in PANDA_DIR
    # make sure that it is PANDA2
    progress("Checking for PANDA in " + PANDA_DIR)
    if not isdir(PANDA_DIR):
        os.chdir(dirname(PANDA_DIR))
        run("rm -f install_ubuntu.sh")
        run("wget {}".format(PANDA_UBUNTU))
        run("bash install_ubuntu.sh")
        os.chdir(LAVA_DIR)
    elif not isfile(join(LAVA_DIR, "tools", "fbi", "panda.mak")) or \
            not isfile(join(PANDA_BUILD_DIR, 'config.log')):
        progress("Building PANDA in " + PANDA_BUILD_DIR)
        try:
            os.makedirs(PANDA_BUILD_DIR)
        except OSError:
            print("Warning: Panda build directory is already there")
        os.chdir(PANDA_DIR)
        run(['git', 'submodule', 'update', '--init', 'dtc'])
        os.chdir(PANDA_BUILD_DIR)
        run([join(PANDA_DIR, 'build.sh')])
        os.chdir(LAVA_DIR)
    # Compile lavaTool inside the docker container.
    progress("Creating $LAVA_DIR/tools/lavaTool/config.mak")
    with open("tools/lavaTool/config.mak", "w") as f:
        LLVM_DOCKER_DIR = '/llvm-{}'.format(LLVM_VERSION)
        f.write(LLVM_MAK.format(LLVM_BUILD_PATH=LLVM_DOCKER_DIR,
                                LLVM_SRC_PATH=LLVM_DOCKER_DIR))
    run_docker(['rm', '-rf', join(LAVA_DIR, 'tools/build')])
    run_docker(['mkdir', '-p', join(LAVA_DIR, 'tools/build')])
    run_docker(['mkdir', '-p', join(LAVA_DIR, 'tools/install')])

    run_docker(['cmake', '-B{}'.format(join(LAVA_DIR, 'tools/build')),
                '-H{}'.format(join(LAVA_DIR, 'tools')),
                '-DCMAKE_INSTALL_PREFIX={}'.format(join(LAVA_DIR,
                                                        'tools/install'))])
    run_docker(['make','--no-print-directory','-j4', 'install', '-C',
                join(LAVA_DIR, 'tools/build/lavaTool')])

    # ensure /etc/apt/sources.list has all of the deb-src lines uncommented
    patch_sources = join(LAVA_DIR, "scripts/patch-sources.py")
    lines = open("/etc/apt/sources.list")
    filt_lines = [line for line in lines if line.strip().startswith("#deb-src")
                  or line.strip().startswith("# deb-src")]
    if len(filt_lines) > 0:
        progress("Uncommenting {} deb-src lines in".format(len(filt_lines)) +
                 "/etc/apt/sources.list")
        run(['sudo', 'python3', patch_sources])

    progress("Checking for ODB orm libraries")
    odb_version = "2.4.0"
    odb_baseurl = "http://www.codesynthesis.com/download/odb/2.4/"
    if not isfile('/usr/bin/odb'):
        os.chdir(BUILD_DIR)
        run("wget {}/odb_{}-1_amd64.deb".format(odb_baseurl, odb_version))
        run("sudo dpkg -i odb_{}-1_amd64.deb".format(odb_version))

    if not isfile('/usr/local/lib/libodb.so') and \
            not isfile('/usr/lib/libodb.so'):
        os.chdir(BUILD_DIR)
        run("wget {}/libodb-{}.tar.gz".format(odb_baseurl, odb_version))
        run("tar -xf libodb-{}.tar.gz".format(odb_version))
        os.chdir("libodb-{}/".format(odb_version))
        run("sh configure")
        run(['make', '-j', str(cpu_count())])
        run("sudo make install")

    if not isfile('/usr/local/lib/libodb-pgsql.so') and \
            not isfile('/usr/lib/libodb-pgsql.so'):
        os.chdir(BUILD_DIR)
        run("wget {}/libodb-pgsql-{}.tar.gz".format(odb_baseurl, odb_version))
        run("tar -xf libodb-pgsql-{}.tar.gz".format(odb_version))
        os.chdir("libodb-pgsql-{}/".format(odb_version))
        run("sh configure")
        run(['make', '-j', str(cpu_count())])
        run("sudo make install")

    progress("Finished installing ODB libraries")

    progress("Installing python dependencies.")
    if command_exited_nonzero("python -c \"import {}\"".format("subprocess32")):
        run("sudo pip install subprocess32")

    # -----------Beginning .mak file stuff -------------------
    # I think this would be useful, but i'm seperating it out
    # in case anyone thinks it's a bad idea
    # the idea is that if someone wants llvm and panda installed in certain
    # locations, they can make their lava.mak ahead of time
    # then setup.py will parse it and configure the environmet to those specs
    os.chdir(LAVA_DIR)

    if not isfile(join(LAVA_DIR, "fbi", "panda.mak")):
        progress("Creating $LAVA_DIR/tools/fbi/panda.mak")
        with open(join(LAVA_DIR, "tools/fbi/panda.mak"), "w") as f:
            f.write(PANDA_MAK.format(PANDA_DIR=PANDA_DIR))

    if not isfile(join(LAVA_DIR, "lava.mak")):
        progress("Creating $LAVA_DIR/lava.mak")
        with open("lava.mak", 'w') as f:
            f.write(PANDA_MAK.format(PANDA_DIR=PANDA_DIR))
            f.write(LLVM_MAK.format(LLVM_BUILD_PATH=LLVM_DOCKER_DIR,
                                    LLVM_SRC_PATH=LLVM_DOCKER_DIR))

    # ----------------End .mak file stuff ---------------------
    progress("Making each component of lava, fbi and lavaTool")
    progress("Compiling fbi")

    os.chdir(join(LAVA_DIR, "tools/build"))
    run("make --no-print-directory -j4 -C fbi install")
    os.chdir(LAVA_DIR)

    return 0


if __name__ == "__main__":
    sys.exit(main())
